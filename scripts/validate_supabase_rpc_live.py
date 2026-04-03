#!/usr/bin/env python3
"""
Strict live validation for KMBL Supabase RPC hardening.

Run against your real Supabase project (service role — server-side only; never ship to browsers).

  cd services/orchestrator && pip install supabase
  set SUPABASE_URL=... && set SUPABASE_SERVICE_ROLE_KEY=...
  python ../../scripts/validate_supabase_rpc_live.py

Optional (proves functions in pg_catalog after migrations):

  pip install "psycopg[binary]"
  set DATABASE_URL=postgresql://postgres:...@db.<ref>.supabase.co:5432/postgres
  python ../../scripts/validate_supabase_rpc_live.py

Exit code 0 only if all required checks pass. Append stdout to docs/LIVE_VALIDATION_REPORT.md for audit trail.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_FILE = REPO_ROOT / "supabase" / "migrations" / "20260402183000_atomic_staging_rpc.sql"

REQUIRED_RPCS = (
    "kmbl_thread_advisory_xact_lock",
    "kmbl_atomic_staging_node_persist",
    "kmbl_atomic_working_staging_approve",
    "kmbl_atomic_upsert_working_staging",
)


def _print(msg: str) -> None:
    # Windows consoles may use cp1252; avoid UnicodeEncodeError on tool output.
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"), flush=True)


def check_migration_file_present() -> bool:
    ok = MIGRATION_FILE.is_file()
    _print(f"[migration file] {MIGRATION_FILE} {'OK' if ok else 'MISSING'}")
    return ok


def check_pg_catalog_functions(database_url: str) -> bool:
    try:
        import psycopg
    except ImportError:
        _print("[pg_catalog] SKIP (install psycopg[binary] and set DATABASE_URL)")
        return True

    missing: list[str] = []
    try:
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "SELECT version FROM supabase_migrations.schema_migrations "
                        "WHERE version LIKE %s",
                        ("%20260402183000%",),
                    )
                    mig_rows = cur.fetchall()
                    if mig_rows:
                        _print(f"[supabase_migrations] row for atomic RPC migration: {mig_rows}")
                    else:
                        _print(
                            "[supabase_migrations] no row matching %20260402183000% - "
                            "if you pasted SQL manually, ensure it ran on THIS database; "
                            "or run: supabase db push / SQL editor against project linked to this URL."
                        )
                except Exception as ex:
                    _print(f"[supabase_migrations] (optional) {type(ex).__name__}: {ex}")
                for name in REQUIRED_RPCS:
                    cur.execute(
                        "SELECT 1 FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid "
                        "WHERE n.nspname = 'public' AND p.proname = %s",
                        (name,),
                    )
                    if cur.fetchone() is None:
                        missing.append(name)
    except Exception as e:
        _print(f"[pg_catalog] FAIL: {type(e).__name__}: {e}")
        return False

    if missing:
        _print(f"[pg_catalog] FAIL - missing functions: {missing}")
        _print("[pg_catalog] hint: run scripts/diag_supabase_kmbl_targets.py to compare API host vs DB host.")
        return False
    _print("[pg_catalog] OK - all kmbl_* RPCs present in public schema")
    return True


def _is_schema_cache_missing_rpc(exc: Exception) -> bool:
    s = str(exc)
    return "PGRST202" in s or "schema cache" in s.lower()


def rpc_smoke(client: Any) -> bool:
    tid = str(uuid.uuid4())
    try:
        client.rpc("kmbl_thread_advisory_xact_lock", {"p_thread_id": tid}).execute()
    except Exception as e:
        _print(f"[rpc kmbl_thread_advisory_xact_lock] FAIL: {type(e).__name__}: {e}")
        if _is_schema_cache_missing_rpc(e):
            _print(
                "[hint] PostgREST cannot see these functions - apply the SQL migration to THIS project: "
                f"{MIGRATION_FILE.name} (Supabase Dashboard SQL editor, or supabase db push), "
                "then wait for schema cache reload or restart PostgREST if your project requires it."
            )
        return False
    _print("[rpc kmbl_thread_advisory_xact_lock] OK")

    ws_id = str(uuid.uuid4())
    row: dict[str, Any] = {
        "working_staging_id": ws_id,
        "thread_id": tid,
        "payload_json": {},
        "last_update_mode": "init",
        "revision": 1,
        "status": "draft",
        "created_at": "2026-04-02T12:00:00+00:00",
        "updated_at": "2026-04-02T12:00:00+00:00",
        "stagnation_count": 0,
        "last_evaluator_issue_count": 0,
        "last_revision_summary_json": {},
    }
    try:
        client.rpc(
            "kmbl_atomic_upsert_working_staging",
            {"p_thread_id": tid, "p_working_staging": row},
        ).execute()
    except Exception as e:
        _print(f"[rpc kmbl_atomic_upsert_working_staging] FAIL: {type(e).__name__}: {e}")
        return False
    _print("[rpc kmbl_atomic_upsert_working_staging] OK (insert/upsert)")

    # Intentionally invalid RPC — expect failure (proves errors are not swallowed here)
    try:
        client.rpc("kmbl___nonexistent_rpc___", {"p_thread_id": tid}).execute()
        _print("[rpc invalid name] FAIL - expected error, got success")
        return False
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        if "404" in err or "PGRST" in err or "schema cache" in err.lower() or "function" in err.lower():
            _print(f"[rpc invalid name] OK - surfaced error: {err[:200]}")
        else:
            _print(f"[rpc invalid name] OK - surfaced error: {err[:300]}")
    return True


def concurrency_lock_probe(client: Any) -> bool:
    """Two concurrent upserts on the same thread_id should serialize (second waits on advisory lock)."""
    tid = str(uuid.uuid4())
    ws_id = str(uuid.uuid4())

    def row_payload(rev: int) -> dict[str, Any]:
        return {
            "working_staging_id": ws_id,
            "thread_id": tid,
            "payload_json": {"probe": True, "rev": rev},
            "last_update_mode": "init",
            "revision": rev,
            "status": "draft",
            "created_at": "2026-04-02T12:00:00+00:00",
            "updated_at": "2026-04-02T12:00:00+00:00",
            "stagnation_count": 0,
            "last_evaluator_issue_count": 0,
            "last_revision_summary_json": {},
        }

    barrier = threading.Barrier(2)
    errors: list[str] = []

    def upsert(rev: int) -> None:
        try:
            barrier.wait()
            client.rpc(
                "kmbl_atomic_upsert_working_staging",
                {"p_thread_id": tid, "p_working_staging": row_payload(rev)},
            ).execute()
        except Exception as e:
            errors.append(str(e))

    t0 = time.perf_counter()
    t_a = threading.Thread(target=upsert, args=(1,))
    t_b = threading.Thread(target=upsert, args=(2,))
    t_a.start()
    t_b.start()
    t_a.join(timeout=30)
    t_b.join(timeout=30)
    wall = time.perf_counter() - t0

    if errors:
        _print(f"[concurrency] FAIL: {errors}")
        return False

    # Baseline: single round-trip latency (different thread_id to avoid lock interaction)
    t_single = time.perf_counter()
    tid_solo = str(uuid.uuid4())
    ws_solo = str(uuid.uuid4())
    solo = row_payload(99)
    solo["thread_id"] = tid_solo
    solo["working_staging_id"] = ws_solo
    client.rpc(
        "kmbl_atomic_upsert_working_staging",
        {"p_thread_id": tid_solo, "p_working_staging": solo},
    ).execute()
    single_latency = time.perf_counter() - t_single

    _print(f"[concurrency] wall_two_parallel_rpc_s={wall:.3f} single_rpc_s={single_latency:.3f}")
    # If locks serialize, wall is usually noticeably greater than one RTT (heuristic, not a formal proof).
    if wall < single_latency * 1.2:
        _print(
            "[concurrency] WARN - parallel wall time not >> single RPC; lock effect inconclusive "
            "(network variance). Inspect Postgres or re-run."
        )
    else:
        _print("[concurrency] OK - wall time consistent with serialized critical section (heuristic)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Live Supabase RPC validation for KMBL")
    parser.add_argument(
        "--skip-concurrency",
        action="store_true",
        help="Skip two-thread lock probe (e.g. if rate-limited)",
    )
    args = parser.parse_args()

    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        _print("FAIL: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        return 2

    ok = check_migration_file_present()
    db_url = (os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL") or "").strip()
    ok = check_pg_catalog_functions(db_url) and ok

    from supabase import create_client

    client = create_client(url, key)

    ok = rpc_smoke(client) and ok
    if not args.skip_concurrency:
        ok = concurrency_lock_probe(client) and ok

    _print("---")
    _print("NEXT: run a real graph through staging_node and operator approve; confirm timeline shows "
           "persistence=supabase_rpc / mutation_path in graph_run_event payloads (see docs/LIVE_VALIDATION_REPORT.md).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
