"""Stable per-run URLs pointing at live working staging (thread-scoped, updates each iteration)."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.config import Settings

_SESSION_NOTE = (
    "Stable for this graph_run_id: redirects to the current working staging for the run's thread. "
    "The HTML preview updates as generator iterations apply — use it to see the latest surface "
    "without re-reading full artifact history. JSON GET returns the full working_staging payload. "
    "The control plane also exposes /habitat/live/{thread_id} for a human-visible live surface "
    "(distinct from frozen staging snapshots for review). "
    "For evaluator/browser grounding during iterate loops, prefer orchestrator_candidate_preview_url "
    "(latest build_candidate for this graph_run) over working_staging preview — see candidate-preview route."
)


def build_session_staging_links_dict(
    settings: Settings,
    *,
    graph_run_id: str,
    thread_id: str,
) -> dict[str, Any]:
    base = (getattr(settings, "orchestrator_public_base_url", "") or "").strip().rstrip("/")
    orch_prev = f"/orchestrator/runs/{graph_run_id}/staging-preview"
    orch_cand = f"/orchestrator/runs/{graph_run_id}/candidate-preview"
    orch_json = f"/orchestrator/working-staging/{thread_id}"
    cp_prev = f"/api/runs/{graph_run_id}/staging-preview"
    cp_live = f"/habitat/live/{thread_id}"
    out: dict[str, Any] = {
        "graph_run_id": graph_run_id,
        "thread_id": thread_id,
        "orchestrator_staging_preview_path": orch_prev,
        "orchestrator_candidate_preview_path": orch_cand,
        "orchestrator_working_staging_json_path": orch_json,
        "control_plane_staging_preview_path": cp_prev,
        "control_plane_live_habitat_path": cp_live,
        "note": _SESSION_NOTE,
    }
    if base:
        out["orchestrator_candidate_preview_url"] = f"{base}{orch_cand}"
        out["orchestrator_staging_preview_url"] = f"{base}{orch_prev}"
        out["orchestrator_working_staging_json_url"] = f"{base}{orch_json}"
    return out


def resolve_evaluator_preview_resolution(
    settings: Settings,
    *,
    graph_run_id: str,
    thread_id: str,
    build_candidate: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolved preview URL plus source metadata for evaluator payloads and policy checks."""
    base_raw = (getattr(settings, "orchestrator_public_base_url", "") or "").strip()
    public_base_configured = bool(base_raw)
    links = build_session_staging_links_dict(
        settings,
        graph_run_id=str(graph_run_id),
        thread_id=str(thread_id),
    )
    cand_prev = links.get("orchestrator_candidate_preview_url")
    orch = links.get("orchestrator_staging_preview_url")
    bc = build_candidate or {}
    bc_pv = bc.get("preview_url")
    bc_preview = bc_pv.strip() if isinstance(bc_pv, str) and bc_pv.strip() else None

    preview_url: str | None = None
    source = "none"
    if isinstance(cand_prev, str) and cand_prev.strip():
        preview_url = cand_prev.strip()
        source = "orchestrator_candidate_preview"
    elif isinstance(orch, str) and orch.strip():
        preview_url = orch.strip()
        source = "orchestrator_staging_preview"
    elif bc_preview:
        preview_url = bc_preview
        source = "build_candidate_preview_url"

    is_abs = False
    if isinstance(preview_url, str) and preview_url.strip():
        s = preview_url.strip()
        is_abs = s.startswith("http://") or s.startswith("https://")

    return {
        "preview_url": preview_url,
        "preview_url_source": source,
        "preview_url_is_absolute": is_abs,
        "orchestrator_public_base_url_configured": public_base_configured,
    }


def resolve_evaluator_preview_url(
    settings: Settings,
    *,
    graph_run_id: str,
    thread_id: str,
    build_candidate: dict[str, Any] | None,
) -> str | None:
    """Prefer latest build_candidate HTML preview; then working_staging preview; then candidate ``preview_url``."""
    res = resolve_evaluator_preview_resolution(
        settings,
        graph_run_id=str(graph_run_id),
        thread_id=str(thread_id),
        build_candidate=build_candidate,
    )
    u = res.get("preview_url")
    return u.strip() if isinstance(u, str) and u.strip() else None


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
