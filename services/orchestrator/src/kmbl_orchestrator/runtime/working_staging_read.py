"""Resilient working_staging reads for graph nodes (iterate path / infra blips)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from kmbl_orchestrator.domain import WorkingStagingRecord
from kmbl_orchestrator.persistence.supabase_infra import classify_supabase_exception
from kmbl_orchestrator.persistence.supabase_repository import SupabaseRepository
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event

if TYPE_CHECKING:
    from kmbl_orchestrator.persistence.repository import Repository

_log = logging.getLogger(__name__)


def get_working_staging_for_thread_resilient(
    repo: "Repository",
    thread_id: UUID,
    *,
    graph_run_id: UUID,
    phase: str,
    iteration_index: int,
) -> WorkingStagingRecord | None:
    """
    Load working staging for a thread.

    On **SupabaseRepository** only: if the read raises ``RuntimeError`` (transport/PostgREST),
    emit ``working_staging_fetch_degraded`` and return ``None`` so the graph can continue when
    facts can be built without DB (e.g. generator iteration > 0 with ``build_candidate`` in state).

    **InMemoryRepository** and non-raising paths are unchanged.

    This does **not** mask logic bugs: unexpected exception types are re-raised.
    """
    if not isinstance(repo, SupabaseRepository):
        return repo.get_working_staging_for_thread(thread_id)
    try:
        return repo.get_working_staging_for_thread(thread_id)
    except RuntimeError as e:
        info = classify_supabase_exception(e)
        payload: dict[str, Any] = {
            "error_kind": "working_staging_read_degraded",
            "phase": phase,
            "thread_id": str(thread_id),
            "iteration_index": iteration_index,
            "exception_type": type(e).__name__,
            "looks_like_non_json_upstream": info.get("looks_like_non_json_upstream"),
            "looks_like_cloudflare": info.get("looks_like_cloudflare"),
            "http_status_hint": info.get("http_status_hint"),
            "message_excerpt": (info.get("message") or "")[:300],
            "body_preview": (info.get("body_preview") or "")[:220],
        }
        append_graph_run_event(
            repo,
            graph_run_id,
            RunEventType.WORKING_STAGING_FETCH_DEGRADED,
            payload,
            thread_id=thread_id,
        )
        _log.warning(
            "working_staging read degraded graph_run_id=%s phase=%s thread_id=%s iter=%s: %s",
            graph_run_id,
            phase,
            thread_id,
            iteration_index,
            info.get("message", str(e))[:200],
        )
        return None
