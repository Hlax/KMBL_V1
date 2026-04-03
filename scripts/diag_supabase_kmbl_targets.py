"""Compare Supabase API URL vs DB URL hosts and list public.kmbl_* (no secrets). Run from services/orchestrator with PYTHONPATH=src."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ORCH = Path(__file__).resolve().parents[1] / "services" / "orchestrator"
sys.path.insert(0, str(ORCH / "src"))
from kmbl_orchestrator.config import Settings  # noqa: E402


def host_only(uri: str) -> str:
    if not uri:
        return "(empty)"
    if uri.startswith("https://") or uri.startswith("http://"):
        from urllib.parse import urlparse

        return urlparse(uri).netloc or uri[:60]
    if "@" in uri:
        tail = uri.split("@", 1)[-1]
        hostpart = tail.split("/")[0]
        return hostpart.rsplit(":", 1)[0] if ":" in hostpart else hostpart
    return uri[:50]


def ref_from_supabase_url(url: str) -> str | None:
    m = re.search(r"https://([a-z0-9]+)\.supabase\.co", url or "")
    return m.group(1) if m else None


def main() -> None:
    s = Settings()
    url = (s.supabase_url or "").strip()
    db = (s.supabase_db_url or "").strip()
    print("SUPABASE_URL host:", host_only(url))
    print("SUPABASE_DB_URL host:", host_only(db))
    r = ref_from_supabase_url(url)
    if r:
        print("project ref from SUPABASE_URL:", r)
        if r in db:
            print("project ref appears in DB URL: yes")
        else:
            print("project ref appears in DB URL: NO (possible mismatch)")
    try:
        import psycopg
    except ImportError:
        print("psycopg not installed")
        return
    if not db:
        print("no SUPABASE_DB_URL")
        return
    try:
        with psycopg.connect(db) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database(), current_user")
                print("connected:", cur.fetchone())
                cur.execute(
                    """
                    SELECT proname FROM pg_proc p
                    JOIN pg_namespace n ON p.pronamespace = n.oid
                    WHERE n.nspname = 'public' AND proname LIKE 'kmbl%'
                    ORDER BY 1
                    """
                )
                rows = [r[0] for r in cur.fetchall()]
                print("public.kmbl_* count:", len(rows))
                print("public.kmbl_*:", rows if rows else "(none)")
                try:
                    cur.execute(
                        """
                        SELECT version FROM supabase_migrations.schema_migrations
                        WHERE version LIKE '%20260402183000%'
                        """
                    )
                    mig = cur.fetchall()
                    print("supabase_migrations match 20260402183000:", mig)
                except Exception as e:
                    print("supabase_migrations table:", type(e).__name__, e)
    except Exception as e:
        print("connect/query failed:", type(e).__name__, e)


if __name__ == "__main__":
    main()
