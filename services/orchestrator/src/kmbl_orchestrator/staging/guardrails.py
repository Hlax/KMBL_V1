"""Guardrails: anti-rot protection for working staging.

Provides configurable thresholds and helpers to prevent working staging
from accumulating junk or drifting into unrecoverable states.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class GuardrailThresholds(BaseModel):
    """Configurable thresholds for working staging guardrails."""

    max_patches_before_forced_rebuild: int = 12
    max_stagnation_iterations: int = 4
    max_stale_artifact_refs: int = 30
    max_retained_checkpoints: int = 25
    max_revision_without_preview: int = 5
    warn_artifact_count: int = 40
    warn_payload_size_kb: int = 500


DEFAULT_GUARDRAILS = GuardrailThresholds()


class GuardrailViolation(BaseModel):
    """A specific guardrail violation."""

    guardrail: str
    value: Any
    threshold: Any
    severity: Literal["warning", "error", "critical"] = "warning"
    message: str = ""
    recommendation: str = ""


class GuardrailEvaluation(BaseModel):
    """Result of evaluating all guardrails."""

    is_healthy: bool = True
    violations: list[GuardrailViolation] = Field(default_factory=list)
    forced_rebuild_required: bool = False
    forced_rebuild_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)


def evaluate_guardrails(
    *,
    revision: int,
    patches_since_rebuild: int,
    stagnation_count: int,
    artifact_count: int,
    checkpoint_count: int,
    has_previewable_html: bool,
    payload_size_bytes: int = 0,
    thresholds: GuardrailThresholds | None = None,
) -> GuardrailEvaluation:
    """Evaluate all guardrails and return violations."""
    t = thresholds or DEFAULT_GUARDRAILS
    violations: list[GuardrailViolation] = []
    warnings: list[str] = []
    forced_rebuild = False
    forced_reason: str | None = None

    if patches_since_rebuild >= t.max_patches_before_forced_rebuild:
        violations.append(GuardrailViolation(
            guardrail="max_patches",
            value=patches_since_rebuild,
            threshold=t.max_patches_before_forced_rebuild,
            severity="critical",
            message=f"Too many patches ({patches_since_rebuild}) since last rebuild",
            recommendation="Force rebuild to reset working staging",
        ))
        forced_rebuild = True
        forced_reason = "max_patches_exceeded"

    if stagnation_count >= t.max_stagnation_iterations:
        violations.append(GuardrailViolation(
            guardrail="max_stagnation",
            value=stagnation_count,
            threshold=t.max_stagnation_iterations,
            severity="error",
            message=f"Stagnation detected: {stagnation_count} iterations without improvement",
            recommendation="Consider rebuild or manual intervention",
        ))
        if not forced_rebuild:
            forced_rebuild = True
            forced_reason = "stagnation_detected"

    if artifact_count > t.max_stale_artifact_refs:
        violations.append(GuardrailViolation(
            guardrail="max_artifacts",
            value=artifact_count,
            threshold=t.max_stale_artifact_refs,
            severity="error",
            message=f"Too many artifacts ({artifact_count}), possible accumulation",
            recommendation="Clean up stale artifacts or rebuild",
        ))
    elif artifact_count > t.warn_artifact_count:
        warnings.append(f"Artifact count ({artifact_count}) approaching limit")

    if revision > 0 and not has_previewable_html and revision >= t.max_revision_without_preview:
        violations.append(GuardrailViolation(
            guardrail="preview_missing",
            value=revision,
            threshold=t.max_revision_without_preview,
            severity="error",
            message=f"No previewable HTML after {revision} revisions",
            recommendation="Ensure generator produces HTML artifacts",
        ))

    if checkpoint_count > t.max_retained_checkpoints:
        warnings.append(
            f"Checkpoint count ({checkpoint_count}) exceeds retention threshold "
            f"({t.max_retained_checkpoints})"
        )

    payload_kb = payload_size_bytes / 1024
    if payload_kb > t.warn_payload_size_kb:
        warnings.append(
            f"Payload size ({payload_kb:.1f}KB) exceeds warning threshold "
            f"({t.warn_payload_size_kb}KB)"
        )

    is_healthy = len([v for v in violations if v.severity != "warning"]) == 0

    return GuardrailEvaluation(
        is_healthy=is_healthy,
        violations=violations,
        forced_rebuild_required=forced_rebuild,
        forced_rebuild_reason=forced_reason,
        warnings=warnings,
    )


def guardrail_evaluation_to_payload(evaluation: GuardrailEvaluation) -> dict[str, Any]:
    """Convert guardrail evaluation to event/log payload."""
    return {
        "is_healthy": evaluation.is_healthy,
        "forced_rebuild_required": evaluation.forced_rebuild_required,
        "forced_rebuild_reason": evaluation.forced_rebuild_reason,
        "violation_count": len(evaluation.violations),
        "violations": [
            {
                "guardrail": v.guardrail,
                "severity": v.severity,
                "message": v.message,
            }
            for v in evaluation.violations
        ],
        "warnings": evaluation.warnings,
    }


def compute_stagnation_count(
    current_issue_count: int,
    previous_issue_count: int,
    current_status: str,
    previous_status: str,
    existing_stagnation_count: int,
) -> int:
    """Compute updated stagnation count based on evaluator progress."""
    if current_status == "pass" and previous_status != "pass":
        return 0
    if current_status == "partial" and previous_status == "fail":
        return 0
    if current_issue_count < previous_issue_count:
        return 0

    if current_issue_count == previous_issue_count and current_status == previous_status:
        return existing_stagnation_count + 1

    if current_issue_count > previous_issue_count:
        return existing_stagnation_count + 1

    return existing_stagnation_count
