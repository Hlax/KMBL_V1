"""Stable per-run URLs pointing at live working staging (thread-scoped, updates each iteration)."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.runtime.preview_reachability import (
    classify_preview_url_host,
    preview_host_blocked_by_openclaw_default,
)

_SESSION_NOTE = (
    "Stable for this graph_run_id: redirects to the current working staging for the run's thread. "
    "The HTML preview updates as generator iterations apply — use it to see the latest surface "
    "without re-reading full artifact history. JSON GET returns the full working_staging payload. "
    "The control plane also exposes /habitat/live/{thread_id} for a human-visible live surface "
    "(distinct from frozen staging snapshots for review). "
    "For evaluator/browser grounding during iterate loops, prefer orchestrator_candidate_preview_url "
    "(latest build_candidate for this graph_run) over working_staging preview — see candidate-preview route."
)


def effective_orchestrator_public_base(settings: Settings) -> tuple[str | None, str]:
    """Return ``(base_url, source)`` where source is configured | derived_local | none."""
    raw = (getattr(settings, "orchestrator_public_base_url", "") or "").strip().rstrip("/")
    if raw:
        return raw, "configured"
    if getattr(settings, "kmbl_preview_derive_local_public_base", True) is False:
        return None, "none"
    if getattr(settings, "kmbl_env", "development") == "production":
        return None, "none"
    port = int(getattr(settings, "orchestrator_port", 8000))
    return f"http://127.0.0.1:{port}", "derived_local"


def build_session_staging_links_dict(
    settings: Settings,
    *,
    graph_run_id: str,
    thread_id: str,
) -> dict[str, Any]:
    base, base_source = effective_orchestrator_public_base(settings)
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
        "orchestrator_public_base_source": base_source,
    }
    if base:
        out["orchestrator_candidate_preview_url"] = f"{base}{orch_cand}"
        out["orchestrator_staging_preview_url"] = f"{base}{orch_prev}"
        out["orchestrator_working_staging_json_url"] = f"{base}{orch_json}"
    return out


def _configured_public_base_trimmed(settings: Settings) -> str | None:
    raw = (getattr(settings, "orchestrator_public_base_url", "") or "").strip().rstrip("/")
    return raw or None


def _is_absolute_http(url: str | None) -> bool:
    if not isinstance(url, str):
        return False
    s = url.strip()
    return s.startswith("http://") or s.startswith("https://")


def _orchestrator_browser_url_candidates(
    settings: Settings,
    graph_run_id: str,
    *,
    allow_private: bool,
) -> list[tuple[str, str]]:
    """
    Orchestrator-absolute preview URLs in priority order for OpenClaw/browser MCP.

    Tries ``KMBL_ORCHESTRATOR_PUBLIC_BASE_URL`` first when set, then the effective base
    (including derived localhost in non-production). Private/loopback bases are skipped
    unless ``allow_private``.
    """
    cand_path = f"/orchestrator/runs/{graph_run_id}/candidate-preview"
    stage_path = f"/orchestrator/runs/{graph_run_id}/staging-preview"
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    def try_base(base_raw: str, base_tag: str) -> None:
        b = base_raw.strip().rstrip("/")
        if not b:
            return
        probe = f"{b}/"
        if not allow_private and preview_host_blocked_by_openclaw_default(probe):
            return
        for path, src in (
            (cand_path, f"orchestrator_candidate_preview_via_{base_tag}"),
            (stage_path, f"orchestrator_staging_preview_via_{base_tag}"),
        ):
            u = f"{b}{path}"
            if u in seen:
                continue
            seen.add(u)
            out.append((u, src))

    cfg = _configured_public_base_trimmed(settings)
    if cfg:
        try_base(cfg, "configured_public_base")
    eff, src = effective_orchestrator_public_base(settings)
    if eff:
        e = eff.strip().rstrip("/")
        c = cfg.strip().rstrip("/") if cfg else ""
        if not c or e != c:
            try_base(eff, str(src))

    return out


def resolve_evaluator_preview_resolution(
    settings: Settings,
    *,
    graph_run_id: str,
    thread_id: str,
    build_candidate: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolved preview URLs and reachability metadata for evaluator payloads and policy checks."""
    public_base_configured = bool((getattr(settings, "orchestrator_public_base_url", "") or "").strip())
    _, base_source = effective_orchestrator_public_base(settings)
    links = build_session_staging_links_dict(
        settings,
        graph_run_id=str(graph_run_id),
        thread_id=str(thread_id),
    )
    cand_prev = links.get("orchestrator_candidate_preview_url")
    orch = links.get("orchestrator_staging_preview_url")
    has_candidate_path = bool(links.get("orchestrator_candidate_preview_path"))
    bc = build_candidate or {}
    bc_pv = bc.get("preview_url")
    bc_preview = bc_pv.strip() if isinstance(bc_pv, str) and bc_pv.strip() else None

    operator_preview_url: str | None = None
    operator_source = "none"
    if isinstance(cand_prev, str) and cand_prev.strip():
        operator_preview_url = cand_prev.strip()
        operator_source = "orchestrator_candidate_preview"
    elif isinstance(orch, str) and orch.strip():
        operator_preview_url = orch.strip()
        operator_source = "orchestrator_staging_preview"
    elif bc_preview:
        operator_preview_url = bc_preview
        operator_source = "build_candidate_preview_url"

    allow_private = bool(getattr(settings, "kmbl_evaluator_allow_private_preview_fetch", False))

    browser_preview_url: str | None = None
    browser_source = "none"
    for u, src in _orchestrator_browser_url_candidates(
        settings,
        graph_run_id,
        allow_private=allow_private,
    ):
        browser_preview_url = u
        browser_source = src
        break
    if browser_preview_url is None and bc_preview and _is_absolute_http(bc_preview):
        if allow_private or not preview_host_blocked_by_openclaw_default(bc_preview):
            browser_preview_url = bc_preview
            browser_source = "build_candidate_preview_url"

    preview_url_host_class: str = (
        classify_preview_url_host(operator_preview_url) if operator_preview_url else "unknown"
    )
    op_is_abs = _is_absolute_http(operator_preview_url)
    br_is_abs = _is_absolute_http(browser_preview_url)

    preview_url_present = bool(operator_preview_url)
    preview_url_absolute = op_is_abs
    preview_url_localhost_or_private = preview_url_host_class in ("localhost", "private_ip")
    preview_url_browser_reachable_expected = bool(browser_preview_url)

    if browser_preview_url:
        preview_grounding_mode = "browser_reachable"
    elif preview_url_present:
        preview_grounding_mode = "operator_local_only"
    else:
        preview_grounding_mode = "unavailable"

    if preview_grounding_mode == "browser_reachable":
        if browser_source.startswith("build_candidate"):
            preview_grounding_reason = "public_build_candidate_preview"
        else:
            preview_grounding_reason = "public_orchestrator_base"
    elif preview_grounding_mode == "operator_local_only":
        preview_grounding_reason = "private_host_blocked_by_gateway_policy"
    else:
        preview_grounding_reason = "missing_absolute_operator_preview"

    preview_grounding = "missing_public_base"
    if op_is_abs and operator_preview_url:
        if operator_source.startswith("orchestrator") and base_source == "derived_local":
            preview_grounding = "derived_local"
        else:
            preview_grounding = "ok"
    elif has_candidate_path and not op_is_abs:
        preview_grounding = "missing_public_base"

    preview_grounding_degraded = preview_grounding == "missing_public_base" or (
        preview_grounding_mode == "operator_local_only"
    )

    preview_grounding_degrade_reason: str | None = None
    if preview_grounding == "missing_public_base":
        preview_grounding_degrade_reason = "missing_absolute_preview_url"
    elif preview_grounding_mode == "operator_local_only":
        preview_grounding_degrade_reason = "private_host_blocked_by_gateway_policy"

    return {
        # Browser / OpenClaw MCP URL (omit when gateway-blocked private/loopback unless allow flag).
        "preview_url": browser_preview_url,
        "preview_url_source": browser_source,
        "preview_url_is_absolute": br_is_abs,
        # Operator-local surface (human control plane / devtools) — may be localhost while preview_url is None.
        "operator_preview_url": operator_preview_url,
        "operator_preview_url_source": operator_source,
        "operator_preview_url_is_absolute": op_is_abs,
        "preview_url_present": preview_url_present,
        "preview_url_absolute": preview_url_absolute,
        "preview_url_localhost_or_private": preview_url_localhost_or_private,
        "preview_url_browser_reachable_expected": preview_url_browser_reachable_expected,
        "preview_grounding_reason": preview_grounding_reason,
        "preview_grounding_mode": preview_grounding_mode,
        "preview_url_host_class": preview_url_host_class,
        "orchestrator_public_base_url_configured": public_base_configured,
        "orchestrator_public_base_source": base_source,
        "preview_grounding": preview_grounding,
        "preview_grounding_degraded": preview_grounding_degraded,
        "preview_grounding_degrade_reason": preview_grounding_degrade_reason,
        "preview_paths_present": has_candidate_path,
        "kmbl_evaluator_allow_private_preview_fetch": allow_private,
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
