"""Repository readiness for run dispatch — cheap REST preflight + operator cache."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.persistence.exceptions import RepositoryDispatchBlockedError
from kmbl_orchestrator.persistence.factory import persisted_graph_runs_available
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.persistence.supabase_infra import classify_supabase_exception
from kmbl_orchestrator.persistence.supabase_repository import SupabaseRepository

_log = logging.getLogger(__name__)

WRITE_PATH_CANARY_RPC = "kmbl_repository_write_path_canary"

# Keys safe to echo to HTTP / operator UIs (no secrets, no raw URLs with credentials).
_SAFE_PREFLIGHT_KEYS = frozenset(
    {
        "state",
        "backend",
        "probe",
        "elapsed_ms",
        "read_elapsed_ms",
        "write_canary_elapsed_ms",
        "row_sample_count",
        "write_path_unproven",
        "write_path_proven",
        "preflight_tier",
        "block_phase",
        "write_canary_status",
        "write_canary_probe",
        "dispatch_context",
        "note",
        "exception_type",
        "looks_like_html",
        "looks_like_cloudflare",
        "looks_like_non_json_upstream",
        "body_preview",
        "http_status_hint",
        "code",
        "message",
        "auth_failure_hint",
        "content_type_hint",
    }
)


def sanitize_repository_preflight_for_operator(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Strip unknown keys and truncate long messages (HTTP 503 / logs)."""
    out: dict[str, Any] = {}
    for k in _SAFE_PREFLIGHT_KEYS:
        if k not in snapshot:
            continue
        v = snapshot[k]
        if k == "message" and isinstance(v, str) and len(v) > 500:
            out[k] = v[:500] + "…"
        else:
            out[k] = v
    return out


def compact_preflight_for_start_response(preflight: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact shape for StartRunResponse (mirrors event_input.kmbl_repository_preflight)."""
    if not preflight:
        return None
    return {
        "state": preflight.get("state"),
        "preflight_tier": preflight.get("preflight_tier"),
        "probe": preflight.get("probe"),
        "elapsed_ms": preflight.get("elapsed_ms"),
        "write_path_proven": preflight.get("write_path_proven"),
        "write_path_unproven": preflight.get("write_path_unproven"),
        "write_canary_status": preflight.get("write_canary_status"),
        "block_phase": preflight.get("block_phase"),
        "dispatch_context": preflight.get("dispatch_context"),
    }


# Process-local: last successful preflight snapshot (for GET /health without hammering Supabase).
_last_preflight_snapshot: dict[str, Any] | None = None
_last_preflight_monotonic: float = 0.0


def reset_repository_preflight_cache_for_tests() -> None:
    """Clear process-local preflight cache (pytest isolation)."""
    global _last_preflight_snapshot, _last_preflight_monotonic
    _last_preflight_snapshot = None
    _last_preflight_monotonic = 0.0


def get_cached_repository_preflight() -> dict[str, Any] | None:
    """Return last recorded preflight snapshot (may be None if no run started yet)."""
    return _last_preflight_snapshot


def _record_preflight(snapshot: dict[str, Any]) -> None:
    global _last_preflight_snapshot, _last_preflight_monotonic
    _last_preflight_snapshot = dict(snapshot)
    _last_preflight_monotonic = time.monotonic()


def probe_supabase_rest_readiness(repo: SupabaseRepository) -> dict[str, Any]:
    """
    Cheap, read-only PostgREST round-trip (``thread`` table, limit 1).

    On success, ``write_path_unproven`` remains True until the RPC canary runs.
    """
    t0 = time.perf_counter()
    try:
        res = repo._client.table("thread").select("thread_id").limit(1).execute()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        n = len(res.data) if getattr(res, "data", None) else 0
        return {
            "state": "healthy",
            "backend": "supabase",
            "probe": "thread_select_limit_1",
            "elapsed_ms": round(elapsed_ms, 2),
            "row_sample_count": n,
            "write_path_unproven": True,
            "note": (
                "Read succeeded against PostgREST JSON; RPC canary not run yet."
            ),
        }
    except Exception as e:
        c = classify_supabase_exception(e)
        auth_hint = _auth_failure_hint(e, c)
        return {
            "state": "blocked",
            "backend": "supabase",
            "probe": "thread_select_limit_1",
            "exception_type": type(e).__name__,
            "message": str(e)[:500],
            "write_path_unproven": True,
            "auth_failure_hint": auth_hint,
            **c,
        }


def _canary_payload_ok(data: Any) -> bool:
    if isinstance(data, dict) and data.get("ok") is True:
        return True
    if isinstance(data, str) and data.strip():
        try:
            parsed = json.loads(data)
            return isinstance(parsed, dict) and parsed.get("ok") is True
        except Exception:
            return False
    return False


def _is_write_canary_rpc_unavailable(exc: BaseException) -> bool:
    """PostgREST: function missing / not exposed — deploy migration, do not treat as hard outage."""
    code = getattr(exc, "code", None)
    if str(code) == "PGRST202":
        return True
    msg = str(exc).lower()
    if "pgrst202" in msg:
        return True
    if "could not find the function" in msg and WRITE_PATH_CANARY_RPC.lower() in msg:
        return True
    return False


def probe_write_path_canary(repo: SupabaseRepository) -> dict[str, Any]:
    """
    Safe write-path canary: invokes ``kmbl_repository_write_path_canary`` via the same
    ``.rpc()`` channel as ``kmbl_atomic_*`` (no durable mutations; function is STABLE).

    Returns status ``ok`` | ``unavailable`` | ``blocked``.
    """
    t0 = time.perf_counter()
    try:
        res = repo._client.rpc(WRITE_PATH_CANARY_RPC, {}).execute()
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        data = getattr(res, "data", None)
        if _canary_payload_ok(data):
            return {
                "status": "ok",
                "probe": WRITE_PATH_CANARY_RPC,
                "elapsed_ms": elapsed_ms,
            }
        return {
            "status": "blocked",
            "probe": WRITE_PATH_CANARY_RPC,
            "elapsed_ms": elapsed_ms,
            "message": "write_path_canary unexpected RPC payload (expected jsonb with ok=true)",
        }
    except Exception as e:
        if _is_write_canary_rpc_unavailable(e):
            return {
                "status": "unavailable",
                "probe": WRITE_PATH_CANARY_RPC,
                "note": (
                    "Canary RPC not deployed or not visible to PostgREST — apply migration "
                    f"{WRITE_PATH_CANARY_RPC}. Atomic RPC readiness not proven."
                ),
            }
        c = classify_supabase_exception(e)
        auth_hint = _auth_failure_hint(e, c)
        return {
            "status": "blocked",
            "probe": WRITE_PATH_CANARY_RPC,
            "exception_type": type(e).__name__,
            "message": str(e)[:500],
            "auth_failure_hint": auth_hint,
            **c,
        }


def _merge_read_write_preflight(
    read: dict[str, Any],
    write: dict[str, Any],
) -> dict[str, Any]:
    """Combine read probe + write canary into one operator-facing snapshot."""
    read_ms = float(read.get("elapsed_ms") or 0.0)
    if read.get("state") != "healthy":
        return {
            "backend": "supabase",
            "state": "blocked",
            "preflight_tier": "repository_blocked",
            "block_phase": "read",
            "probe": read.get("probe", "thread_select_limit_1"),
            "elapsed_ms": read.get("elapsed_ms"),
            "read_elapsed_ms": read.get("elapsed_ms"),
            "write_canary_elapsed_ms": None,
            "write_path_proven": False,
            "write_path_unproven": True,
            "write_canary_status": "skipped",
            "write_canary_probe": WRITE_PATH_CANARY_RPC,
            "note": read.get("note"),
            **{k: v for k, v in read.items() if k not in ("state", "probe", "elapsed_ms", "backend", "note")},
        }

    wstatus = write.get("status")
    write_ms = float(write.get("elapsed_ms") or 0.0) if write.get("elapsed_ms") is not None else 0.0
    total_ms = round(read_ms + write_ms, 2)

    if wstatus == "ok":
        tier = "healthy_write_proven"
        overall_state = "healthy"
        wp = True
        wun = False
        block_phase = None
        note = (
            "REST read + non-mutating RPC canary succeeded (same PostgREST rpc channel as atomic writes). "
            "Does not exercise pg_advisory_xact_lock or full kmbl_atomic_* transaction bodies."
        )
    elif wstatus == "unavailable":
        tier = "healthy_write_unproven"
        overall_state = "healthy"
        wp = False
        wun = True
        block_phase = None
        note = write.get("note") or "Write canary unavailable."
    else:
        tier = "write_path_blocked"
        overall_state = "blocked"
        wp = False
        wun = True
        block_phase = "write_canary"
        note = "Write-path canary failed; atomic RPC persistence is likely blocked."

    out: dict[str, Any] = {
        "backend": "supabase",
        "state": overall_state,
        "preflight_tier": tier,
        "block_phase": block_phase,
        "probe": f"{read.get('probe', 'thread_select_limit_1')}+{write.get('probe', WRITE_PATH_CANARY_RPC)}",
        "elapsed_ms": total_ms,
        "read_elapsed_ms": read.get("elapsed_ms"),
        "write_canary_elapsed_ms": write.get("elapsed_ms"),
        "write_path_proven": wp,
        "write_path_unproven": wun,
        "write_canary_status": wstatus,
        "write_canary_probe": write.get("probe", WRITE_PATH_CANARY_RPC),
        "note": note,
        "row_sample_count": read.get("row_sample_count"),
    }

    if tier == "write_path_blocked":
        for k, v in write.items():
            if k in ("status", "probe", "elapsed_ms"):
                continue
            if k not in out:
                out[k] = v
    return out


def _auth_failure_hint(exc: BaseException, c: dict[str, Any]) -> str | None:
    s = (str(exc) + str(c.get("message", "")) + str(c.get("details", ""))).lower()
    if "jwt" in s or ("invalid" in s and "token" in s):
        return "check_SUPABASE_SERVICE_ROLE_KEY"
    if "401" in s or c.get("http_status_hint") == "401":
        return "unauthorized_check_service_role_key"
    if "403" in s or c.get("http_status_hint") == "403":
        return "forbidden_check_rls_or_key"
    return None


def require_repository_dispatch_healthy(
    repo: Repository,
    settings: Settings,
    *,
    context: str,
) -> dict[str, Any] | None:
    """
    Run preflight when persistence is Supabase; raise ``RepositoryDispatchBlockedError`` if blocked.

    Returns a compact snapshot to merge into ``event_input`` on success, or ``None`` for in-memory.
    """
    if not persisted_graph_runs_available(settings):
        return None
    if not isinstance(repo, SupabaseRepository):
        return None

    read_snap = probe_supabase_rest_readiness(repo)
    if read_snap.get("state") == "blocked":
        merged = _merge_read_write_preflight(
            read_snap,
            {"status": "skipped", "probe": WRITE_PATH_CANARY_RPC},
        )
        merged["dispatch_context"] = context
        _record_preflight(merged)
        _log.error(
            "repository_preflight blocked phase=read context=%s looks_non_json=%s cf=%s",
            context,
            merged.get("looks_like_non_json_upstream"),
            merged.get("looks_like_cloudflare"),
        )
        raise RepositoryDispatchBlockedError(
            merged,
            message=(
                "Supabase REST preflight failed — fix SUPABASE_URL / service role key / network "
                f"before starting a run (context={context})."
            ),
        )

    write_snap = probe_write_path_canary(repo)
    merged = _merge_read_write_preflight(read_snap, write_snap)
    merged["dispatch_context"] = context
    _record_preflight(merged)

    if merged.get("state") == "blocked":
        _log.error(
            "repository_preflight blocked phase=write_canary context=%s tier=%s looks_non_json=%s",
            context,
            merged.get("preflight_tier"),
            merged.get("looks_like_non_json_upstream"),
        )
        raise RepositoryDispatchBlockedError(
            merged,
            message=(
                "Supabase write-path canary failed — RPC channel unusable; fix DB migration / "
                f"keys / network before starting a run (context={context})."
            ),
        )

    if merged.get("preflight_tier") == "healthy_write_unproven":
        _log.warning(
            "repository_preflight write_canary_unavailable context=%s — allow run with write_path_unproven",
            context,
        )

    return merged


def merge_preflight_into_event_input(
    event_input: dict[str, Any],
    preflight: dict[str, Any] | None,
) -> dict[str, Any]:
    if not preflight:
        return event_input
    kmbl_pf: dict[str, Any] = {
        "state": preflight.get("state"),
        "preflight_tier": preflight.get("preflight_tier"),
        "probe": preflight.get("probe"),
        "elapsed_ms": preflight.get("elapsed_ms"),
        "write_path_proven": preflight.get("write_path_proven"),
        "write_path_unproven": preflight.get("write_path_unproven"),
        "write_canary_status": preflight.get("write_canary_status"),
        "block_phase": preflight.get("block_phase"),
        "dispatch_context": preflight.get("dispatch_context"),
    }
    return {**event_input, "kmbl_repository_preflight": kmbl_pf}
