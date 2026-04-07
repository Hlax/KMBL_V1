"""Orchestrator hints for generator retries (refine vs pivot, layout pivot)."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.runtime.demo_preview_grounding import (
    GROUNDING_ISSUE_CODE,
    is_grounding_only_partial,
)


def _design_rubric_suggests_pivot(metrics: dict[str, Any]) -> bool:
    """Low design_quality + originality on partial builds → encourage aesthetic pivot."""
    dr = metrics.get("design_rubric")
    if not isinstance(dr, dict):
        return False
    dq = dr.get("design_quality")
    ori = dr.get("originality")
    if isinstance(dq, (int, float)) and isinstance(ori, (int, float)):
        return float(dq) <= 2.0 and float(ori) <= 2.0
    return False


def preview_metrics_indicate_unhealthy(metrics: dict[str, Any]) -> bool:
    """True when evaluator (or merged harness) reports preview/surface not OK."""
    if metrics.get("preview_load_failed") is True:
        return True
    if metrics.get("preview_unhealthy") is True:
        return True
    prev = metrics.get("preview")
    if isinstance(prev, dict):
        if prev.get("loaded") is False:
            return True
        if prev.get("ok") is False:
            return True
    st = metrics.get("static_preview")
    if isinstance(st, dict) and st.get("ok") is False:
        return True
    return False


def build_iteration_plan_for_generator(
    evaluation_report: dict[str, Any] | None,
    *,
    stagnation_count: int = 0,
    pressure_recommendation: str | None = None,
) -> dict[str, Any] | None:
    """Structured hint: prior evaluator output is the amendment plan; pivot vs refine.

    Mirrors Anthropic-style harness: refine when trending; pivot when duplicate, fail,
    stagnation, rebuild pressure, or very low design rubric on partial.
    """
    if not isinstance(evaluation_report, dict) or not evaluation_report:
        return None
    metrics = (
        evaluation_report.get("metrics")
        if isinstance(evaluation_report.get("metrics"), dict)
        else {}
    )
    status = str(evaluation_report.get("status") or "fail")
    issues = evaluation_report.get("issues")

    # Strip non-actionable grounding issues so they don't inflate issue_count
    # or mislead pivot/refine decisions.  For grounding-only partials this
    # results in issue_count=0, which is the correct signal to the generator.
    grounding_only = is_grounding_only_partial(metrics)
    if isinstance(issues, list):
        issues = [
            iss for iss in issues
            if not (isinstance(iss, dict) and iss.get("code") == GROUNDING_ISSUE_CODE)
        ]

    issue_count = len(issues) if isinstance(issues, list) else 0
    duplicate = metrics.get("duplicate_rejection") is True
    rubric_pivot = _design_rubric_suggests_pivot(metrics) and status == "partial"
    stagnation_pivot = stagnation_count >= 3
    pressure_pivot = pressure_recommendation == "rebuild"

    pivot_hard = (
        status == "fail"
        or duplicate
        or stagnation_pivot
        or pressure_pivot
        or rubric_pivot
    )
    iteration_strategy: str = "pivot" if pivot_hard else "refine"

    return {
        "treat_feedback_as_amendment_plan": True,
        "pivot_layout_strategy": pivot_hard,
        "iteration_strategy": iteration_strategy,
        "evaluator_status": status,
        "duplicate_rejection": duplicate,
        "issue_count": issue_count,
        "headline": evaluation_report.get("summary"),
        "stagnation_count": stagnation_count,
        "pressure_recommendation": pressure_recommendation,
        # Explicit flag so generator knows partial was caused by infra, not build quality.
        "grounding_only_partial": grounding_only,
    }
