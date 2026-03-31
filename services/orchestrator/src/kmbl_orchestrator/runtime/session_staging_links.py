"""Stable per-run URLs pointing at live working staging (thread-scoped, updates each iteration)."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.config import Settings

_SESSION_NOTE = (
    "Stable for this graph_run_id: redirects to the current working staging for the run's thread. "
    "The HTML preview updates as generator iterations apply — use it to see the latest surface "
    "without re-reading full artifact history. JSON GET returns the full working_staging payload. "
    "The control plane also exposes /habitat/live/{thread_id} for a human-visible live surface "
    "(distinct from frozen staging snapshots for review)."
)


def build_session_staging_links_dict(
    settings: Settings,
    *,
    graph_run_id: str,
    thread_id: str,
) -> dict[str, Any]:
    base = (getattr(settings, "orchestrator_public_base_url", "") or "").strip().rstrip("/")
    orch_prev = f"/orchestrator/runs/{graph_run_id}/staging-preview"
    orch_json = f"/orchestrator/working-staging/{thread_id}"
    cp_prev = f"/api/runs/{graph_run_id}/staging-preview"
    cp_live = f"/habitat/live/{thread_id}"
    out: dict[str, Any] = {
        "graph_run_id": graph_run_id,
        "thread_id": thread_id,
        "orchestrator_staging_preview_path": orch_prev,
        "orchestrator_working_staging_json_path": orch_json,
        "control_plane_staging_preview_path": cp_prev,
        "control_plane_live_habitat_path": cp_live,
        "note": _SESSION_NOTE,
    }
    if base:
        out["orchestrator_staging_preview_url"] = f"{base}{orch_prev}"
        out["orchestrator_working_staging_json_url"] = f"{base}{orch_json}"
    return out


def resolve_evaluator_preview_url(
    settings: Settings,
    *,
    graph_run_id: str,
    thread_id: str,
    build_candidate: dict[str, Any] | None,
) -> str | None:
    """Prefer orchestrator assembled staging preview URL; fall back to candidate ``preview_url``."""
    links = build_session_staging_links_dict(
        settings,
        graph_run_id=str(graph_run_id),
        thread_id=str(thread_id),
    )
    orch = links.get("orchestrator_staging_preview_url")
    if isinstance(orch, str) and orch.strip():
        return orch.strip()
    bc = build_candidate or {}
    cand = bc.get("preview_url")
    if isinstance(cand, str) and cand.strip():
        return cand.strip()
    return None


def merge_session_staging_into_event_input(
    settings: Settings,
    event_input: dict[str, Any] | None,
    *,
    graph_run_id: str | None,
    thread_id: str | None,
) -> dict[str, Any]:
    ei = dict(event_input or {})
    if not graph_run_id or not thread_id:
        return ei
    ei["kmbl_session_staging"] = build_session_staging_links_dict(
        settings,
        graph_run_id=str(graph_run_id),
        thread_id=str(thread_id),
    )
    return ei
