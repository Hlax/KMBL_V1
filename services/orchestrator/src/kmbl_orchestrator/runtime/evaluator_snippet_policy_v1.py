"""
Deterministic policy: when evaluator LLM needs ``kmbl_evaluator_artifact_snippets_v1`` vs summary + preview only.

Deterministic gates always use persisted full refs via ``merge_slim_with_full_artifacts_for_gates``;
this module only governs **model-facing** payload bulk.
"""

from __future__ import annotations

from typing import Any, Protocol

from kmbl_orchestrator.runtime.preview_reachability import preview_host_blocked_by_openclaw_default


class _SnippetSettings(Protocol):
    orchestrator_smoke_contract_evaluator: bool
    kmbl_evaluator_force_snippets: bool


def should_omit_evaluator_snippets_from_llm_payload(
    *,
    bc_slim: dict[str, Any],
    skip_llm: bool,
    preview_url: str | None,
    preview_resolution: dict[str, Any],
    settings: _SnippetSettings,
) -> tuple[bool, str]:
    """
    Return (omit_snippets, reason_code).

    When ``omit_snippets`` is True, drop ``kmbl_evaluator_artifact_snippets_v1`` from the evaluator
    invoke payload (and mirrored keys under ``build_candidate``).
    """
    if skip_llm:
        return True, "evaluator_llm_skipped"
    if settings.orchestrator_smoke_contract_evaluator:
        return False, "smoke_contract_evaluator_payload_fallback"
    if getattr(settings, "kmbl_evaluator_force_snippets", False):
        return False, "kmbl_evaluator_force_snippets"

    s2 = bc_slim.get("kmbl_build_candidate_summary_v2")
    if not isinstance(s2, dict):
        return False, "no_summary_v2_include_snippets"

    eps = s2.get("entrypoints")
    if not isinstance(eps, list) or len(eps) == 0:
        return False, "summary_v2_missing_entrypoints"

    pr = s2.get("preview_readiness") if isinstance(s2.get("preview_readiness"), dict) else {}
    if not pr.get("has_resolved_entrypoints"):
        return False, "summary_v2_preview_readiness_false"

    if not preview_url:
        if preview_resolution.get("operator_preview_url"):
            return False, "operator_preview_not_browser_reachable_openclaw"
        return False, "no_preview_url"

    if not preview_resolution.get("preview_url_is_absolute"):
        return False, "preview_url_not_absolute"

    return True, "summary_v2_preview_grounding_sufficient"


def should_prebuild_snippets_for_graph_state(
    *,
    summary_v2: dict[str, Any] | None,
    preview_url_hint: str | None,
) -> bool:
    """
    Return True if ``kmbl_evaluator_artifact_snippets_v1`` should be precomputed for graph checkpoints.

    Returns False when v2 + absolute http preview hint suffice (omit snippets from state); the
    evaluator node re-checks with ``preview_resolution`` before invoke.
    """
    if not isinstance(summary_v2, dict):
        return True
    eps = summary_v2.get("entrypoints")
    if not isinstance(eps, list) or not eps:
        return True
    pr = summary_v2.get("preview_readiness") if isinstance(summary_v2.get("preview_readiness"), dict) else {}
    if not pr.get("has_resolved_entrypoints"):
        return True
    pu = preview_url_hint.strip() if isinstance(preview_url_hint, str) else ""
    if pu.lower().startswith("http"):
        if preview_host_blocked_by_openclaw_default(pu):
            return True
        return False
    return True
