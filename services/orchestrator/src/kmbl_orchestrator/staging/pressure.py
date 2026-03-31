"""Pressure evaluation: health signals to guide patch vs rebuild decisions.

Provides a generic pressure model that aggregates multiple signals to determine
whether patching remains appropriate or rebuild is safer. Signals are configurable
via thresholds and produce inspectable/debuggable results.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PressureThresholds(BaseModel):
    """Configurable thresholds for pressure evaluation.

    Defaults are reasonable starting points; can be overridden per deployment.
    """

    max_patches_before_rebuild_consideration: int = 8
    max_stagnation_iterations: int = 3
    max_unresolved_issues_for_patch: int = 5
    max_artifact_refs_for_healthy_surface: int = 50
    min_evaluator_status_for_patch: list[str] = Field(
        default_factory=lambda: ["pass", "partial"]
    )


DEFAULT_THRESHOLDS = PressureThresholds()


class PressureSignal(BaseModel):
    """One pressure signal with its assessment."""

    signal_name: str
    value: Any
    threshold: Any
    exceeded: bool
    weight: float = 1.0
    explanation: str = ""


class PressureEvaluation(BaseModel):
    """Aggregated pressure evaluation result.

    Explainable: each contributing signal is listed with its value and threshold.
    """

    should_rebuild: bool
    rebuild_reason: str | None = None
    pressure_score: float = 0.0
    signals: list[PressureSignal] = Field(default_factory=list)
    recommendation: Literal["patch", "rebuild", "neutral"] = "neutral"


def evaluate_staging_pressure(
    *,
    revision: int,
    patches_since_last_rebuild: int,
    evaluator_status: str,
    unresolved_issue_count: int,
    stagnation_iterations: int,
    total_artifact_count: int,
    has_previewable_html: bool,
    thresholds: PressureThresholds | None = None,
) -> PressureEvaluation:
    """Evaluate pressure signals and determine if rebuild is warranted.

    Returns an explainable evaluation with each signal's contribution.
    """
    t = thresholds or DEFAULT_THRESHOLDS
    signals: list[PressureSignal] = []
    total_weight = 0.0
    exceeded_weight = 0.0

    if revision == 0:
        return PressureEvaluation(
            should_rebuild=True,
            rebuild_reason="initial_build",
            pressure_score=1.0,
            signals=[],
            recommendation="rebuild",
        )

    patches_exceeded = patches_since_last_rebuild >= t.max_patches_before_rebuild_consideration
    signals.append(PressureSignal(
        signal_name="patches_since_rebuild",
        value=patches_since_last_rebuild,
        threshold=t.max_patches_before_rebuild_consideration,
        exceeded=patches_exceeded,
        weight=2.0,
        explanation=f"{patches_since_last_rebuild} patches since last rebuild (threshold: {t.max_patches_before_rebuild_consideration})",
    ))
    total_weight += 2.0
    if patches_exceeded:
        exceeded_weight += 2.0

    status_ok = evaluator_status in t.min_evaluator_status_for_patch
    signals.append(PressureSignal(
        signal_name="evaluator_status",
        value=evaluator_status,
        threshold=t.min_evaluator_status_for_patch,
        exceeded=not status_ok,
        weight=3.0,
        explanation=f"evaluator status '{evaluator_status}' (acceptable: {t.min_evaluator_status_for_patch})",
    ))
    total_weight += 3.0
    if not status_ok:
        exceeded_weight += 3.0

    stagnation_exceeded = stagnation_iterations >= t.max_stagnation_iterations
    signals.append(PressureSignal(
        signal_name="stagnation_iterations",
        value=stagnation_iterations,
        threshold=t.max_stagnation_iterations,
        exceeded=stagnation_exceeded,
        weight=2.0,
        explanation=f"{stagnation_iterations} iterations without improvement (threshold: {t.max_stagnation_iterations})",
    ))
    total_weight += 2.0
    if stagnation_exceeded:
        exceeded_weight += 2.0

    issues_exceeded = unresolved_issue_count > t.max_unresolved_issues_for_patch
    signals.append(PressureSignal(
        signal_name="unresolved_issues",
        value=unresolved_issue_count,
        threshold=t.max_unresolved_issues_for_patch,
        exceeded=issues_exceeded,
        weight=1.5,
        explanation=f"{unresolved_issue_count} unresolved issues (threshold: {t.max_unresolved_issues_for_patch})",
    ))
    total_weight += 1.5
    if issues_exceeded:
        exceeded_weight += 1.5

    artifact_bloat = total_artifact_count > t.max_artifact_refs_for_healthy_surface
    signals.append(PressureSignal(
        signal_name="artifact_count",
        value=total_artifact_count,
        threshold=t.max_artifact_refs_for_healthy_surface,
        exceeded=artifact_bloat,
        weight=1.0,
        explanation=f"{total_artifact_count} artifacts (threshold: {t.max_artifact_refs_for_healthy_surface})",
    ))
    total_weight += 1.0
    if artifact_bloat:
        exceeded_weight += 1.0

    preview_missing = revision > 0 and not has_previewable_html
    signals.append(PressureSignal(
        signal_name="preview_missing",
        value=not has_previewable_html,
        threshold=False,
        exceeded=preview_missing,
        weight=1.5,
        explanation="no previewable HTML after patches" if preview_missing else "has previewable HTML",
    ))
    total_weight += 1.5
    if preview_missing:
        exceeded_weight += 1.5

    pressure_score = exceeded_weight / total_weight if total_weight > 0 else 0.0

    should_rebuild = False
    rebuild_reason = None
    recommendation: Literal["patch", "rebuild", "neutral"] = "neutral"

    if not status_ok:
        should_rebuild = True
        rebuild_reason = "evaluator_fail_status"
        recommendation = "rebuild"
    elif pressure_score >= 0.5:
        should_rebuild = True
        exceeded_names = [s.signal_name for s in signals if s.exceeded]
        rebuild_reason = f"pressure_threshold_exceeded ({', '.join(exceeded_names)})"
        recommendation = "rebuild"
    elif pressure_score >= 0.3:
        recommendation = "neutral"
    else:
        recommendation = "patch"

    return PressureEvaluation(
        should_rebuild=should_rebuild,
        rebuild_reason=rebuild_reason,
        pressure_score=round(pressure_score, 3),
        signals=signals,
        recommendation=recommendation,
    )


def pressure_evaluation_to_event_payload(evaluation: PressureEvaluation) -> dict[str, Any]:
    """Convert pressure evaluation to a compact event payload."""
    return {
        "should_rebuild": evaluation.should_rebuild,
        "rebuild_reason": evaluation.rebuild_reason,
        "pressure_score": evaluation.pressure_score,
        "recommendation": evaluation.recommendation,
        "signal_summary": {s.signal_name: s.exceeded for s in evaluation.signals},
    }


def count_patches_since_rebuild(
    revision: int,
    last_rebuild_revision: int | None,
) -> int:
    """Count patches since the last rebuild (or since revision 0)."""
    base = last_rebuild_revision if last_rebuild_revision is not None else 0
    return max(0, revision - base)
