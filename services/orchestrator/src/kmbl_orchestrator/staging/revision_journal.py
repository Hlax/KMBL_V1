"""Revision journal: structured metadata for working staging mutations.

Provides typed revision summaries that explain what changed, why, and how —
enabling operators and downstream tools to understand working staging evolution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RevisionModeReason(BaseModel):
    """Explains why patch vs rebuild was chosen for a revision."""

    category: Literal[
        "initial_build",
        "incremental_improvement",
        "destructive_replace",
        "pressure_threshold_exceeded",
        "stagnation_detected",
        "preview_missing",
        "operator_rollback_recovery",
        "evaluator_fail_status",
        "manual_fresh_rebuild",
    ]
    explanation: str = ""
    contributing_factors: list[str] = Field(default_factory=list)


class EvaluatorInfluence(BaseModel):
    """Summary of evaluator state that influenced the revision decision."""

    status: str
    issue_count: int = 0
    issue_categories: list[str] = Field(default_factory=list)
    improvement_signal: Literal["improved", "regressed", "neutral", "unknown"] = "unknown"


class CheckpointContext(BaseModel):
    """Checkpoint information for a revision."""

    checkpoint_created: bool = False
    checkpoint_id: str | None = None
    checkpoint_reason: str | None = None


class ArtifactDelta(BaseModel):
    """Summary of artifact changes in a revision."""

    artifacts_added: int = 0
    artifacts_replaced: int = 0
    artifacts_removed: int = 0
    total_artifact_count: int = 0
    has_previewable_html: bool = False


class RevisionSummary(BaseModel):
    """Compact structured summary of a working staging revision.

    Persisted as part of working staging state and emitted in events,
    enabling operators to understand revision history without parsing raw payloads.
    """

    revision: int
    previous_revision: int
    update_mode: Literal["patch", "rebuild", "init", "rollback"]
    mode_reason: RevisionModeReason
    evaluator_influence: EvaluatorInfluence | None = None
    artifact_delta: ArtifactDelta | None = None
    checkpoint_context: CheckpointContext | None = None
    outcome_assessment: Literal["progress", "regression", "neutral", "unknown"] = "unknown"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def build_revision_summary(
    *,
    revision: int,
    previous_revision: int,
    update_mode: Literal["patch", "rebuild", "init", "rollback"],
    mode_reason_category: str,
    mode_reason_explanation: str = "",
    contributing_factors: list[str] | None = None,
    evaluator_status: str | None = None,
    evaluator_issue_count: int = 0,
    evaluator_issue_categories: list[str] | None = None,
    improvement_signal: str = "unknown",
    artifacts_added: int = 0,
    artifacts_replaced: int = 0,
    artifacts_removed: int = 0,
    total_artifact_count: int = 0,
    has_previewable_html: bool = False,
    checkpoint_created: bool = False,
    checkpoint_id: UUID | None = None,
    checkpoint_reason: str | None = None,
    outcome_assessment: str = "unknown",
) -> RevisionSummary:
    """Build a revision summary with all context."""
    mode_reason = RevisionModeReason(
        category=mode_reason_category,  # type: ignore[arg-type]
        explanation=mode_reason_explanation,
        contributing_factors=contributing_factors or [],
    )

    evaluator_influence = None
    if evaluator_status is not None:
        evaluator_influence = EvaluatorInfluence(
            status=evaluator_status,
            issue_count=evaluator_issue_count,
            issue_categories=evaluator_issue_categories or [],
            improvement_signal=improvement_signal,  # type: ignore[arg-type]
        )

    artifact_delta = ArtifactDelta(
        artifacts_added=artifacts_added,
        artifacts_replaced=artifacts_replaced,
        artifacts_removed=artifacts_removed,
        total_artifact_count=total_artifact_count,
        has_previewable_html=has_previewable_html,
    )

    checkpoint_context = None
    if checkpoint_created or checkpoint_id:
        checkpoint_context = CheckpointContext(
            checkpoint_created=checkpoint_created,
            checkpoint_id=str(checkpoint_id) if checkpoint_id else None,
            checkpoint_reason=checkpoint_reason,
        )

    return RevisionSummary(
        revision=revision,
        previous_revision=previous_revision,
        update_mode=update_mode,
        mode_reason=mode_reason,
        evaluator_influence=evaluator_influence,
        artifact_delta=artifact_delta,
        checkpoint_context=checkpoint_context,
        outcome_assessment=outcome_assessment,  # type: ignore[arg-type]
    )


def revision_summary_to_event_payload(summary: RevisionSummary) -> dict[str, Any]:
    """Convert revision summary to an event payload dict."""
    return summary.model_dump(mode="json", exclude_none=True)


def compute_artifact_delta(
    before_refs: list[Any],
    after_refs: list[Any],
) -> ArtifactDelta:
    """Compute the artifact changes between two states."""
    before_paths = set()
    for ref in before_refs:
        if isinstance(ref, dict):
            path = ref.get("path", "")
            if path:
                before_paths.add(path)

    after_paths = set()
    has_html = False
    for ref in after_refs:
        if isinstance(ref, dict):
            path = ref.get("path", "")
            if path:
                after_paths.add(path)
            if ref.get("role") == "static_frontend_file_v1" and ref.get("language") == "html":
                has_html = True

    added = after_paths - before_paths
    removed = before_paths - after_paths
    replaced = before_paths & after_paths

    return ArtifactDelta(
        artifacts_added=len(added),
        artifacts_replaced=len(replaced),
        artifacts_removed=len(removed),
        total_artifact_count=len(after_paths),
        has_previewable_html=has_html,
    )


def extract_issue_categories(issues: list[Any]) -> list[str]:
    """Extract unique issue categories/types from evaluator issues."""
    categories = set()
    for issue in issues:
        if isinstance(issue, dict):
            cat = issue.get("category") or issue.get("type") or issue.get("severity")
            if isinstance(cat, str) and cat.strip():
                categories.add(cat.strip().lower())
    return sorted(categories)[:10]
