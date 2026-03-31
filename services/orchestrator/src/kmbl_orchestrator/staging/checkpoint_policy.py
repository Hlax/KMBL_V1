"""
Staging checkpoint policy — when to create and retain working staging checkpoints.

Provides typed decisions for pre-rebuild safety snapshots, first-previewable milestones,
and patch milestones. All checkpoint decisions are derived from this module; callers
in working_staging_ops.py should not encode checkpoint logic inline.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from kmbl_orchestrator.domain import WorkingStagingRecord


class CheckpointReason(BaseModel):
    """Structured reason for checkpoint creation."""

    category: Literal[
        "pre_rebuild_safety",
        "first_previewable_state",
        "post_patch_milestone",
        "pre_approval_freeze",
        "rollback_anchor",
        "operator_manual",
        "stagnation_recovery",
        "pressure_threshold",
    ]
    explanation: str = ""
    triggered_by: str = ""


class CheckpointDecision(BaseModel):
    """Decision about whether to create a checkpoint."""

    should_checkpoint: bool = False
    reason: CheckpointReason | None = None
    priority: Literal["high", "medium", "low"] = "low"


class CheckpointRetentionPolicy(BaseModel):
    """Policy for checkpoint retention (guardrails against checkpoint spam)."""

    max_checkpoints_per_working_staging: int = 20
    retain_all_pre_rebuild: bool = True
    retain_all_first_previewable: bool = True
    retain_all_pre_approval: bool = True
    max_post_patch_checkpoints: int = 10


DEFAULT_RETENTION_POLICY = CheckpointRetentionPolicy()


def decide_pre_update_checkpoint(
    *,
    working_staging: WorkingStagingRecord,
    update_mode: Literal["patch", "rebuild"],
    pressure_score: float = 0.0,
) -> CheckpointDecision:
    """Decide if a checkpoint should be created BEFORE applying an update."""
    if update_mode == "rebuild" and working_staging.revision > 0:
        return CheckpointDecision(
            should_checkpoint=True,
            reason=CheckpointReason(
                category="pre_rebuild_safety",
                explanation="Checkpoint before destructive rebuild to enable rollback",
                triggered_by="rebuild_mode",
            ),
            priority="high",
        )

    if pressure_score >= 0.5 and working_staging.revision > 0:
        return CheckpointDecision(
            should_checkpoint=True,
            reason=CheckpointReason(
                category="pressure_threshold",
                explanation=f"Checkpoint due to high pressure score ({pressure_score:.2f})",
                triggered_by="pressure_evaluation",
            ),
            priority="medium",
        )

    return CheckpointDecision(should_checkpoint=False)


def decide_post_update_checkpoint(
    *,
    before: WorkingStagingRecord,
    after: WorkingStagingRecord,
    update_mode: Literal["patch", "rebuild"],
    is_first_previewable: bool = False,
    is_milestone: bool = False,
) -> CheckpointDecision:
    """Decide if a checkpoint should be created AFTER applying an update."""
    if is_first_previewable:
        return CheckpointDecision(
            should_checkpoint=True,
            reason=CheckpointReason(
                category="first_previewable_state",
                explanation="First time working staging has previewable HTML",
                triggered_by="previewable_html_check",
            ),
            priority="high",
        )

    if update_mode == "patch":
        if is_milestone or (after.revision > 0 and after.revision % 3 == 0):
            return CheckpointDecision(
                should_checkpoint=True,
                reason=CheckpointReason(
                    category="post_patch_milestone",
                    explanation=f"Milestone checkpoint at revision {after.revision}",
                    triggered_by="patch_mode",
                ),
                priority="medium",
            )

    return CheckpointDecision(should_checkpoint=False)


def decide_approval_checkpoint(
    working_staging: WorkingStagingRecord,
) -> CheckpointDecision:
    """Decide checkpoint creation for approval/freeze operations."""
    if working_staging.revision > 0:
        return CheckpointDecision(
            should_checkpoint=True,
            reason=CheckpointReason(
                category="pre_approval_freeze",
                explanation="Checkpoint before freezing working staging for publication",
                triggered_by="approval_operation",
            ),
            priority="high",
        )
    return CheckpointDecision(should_checkpoint=False)


def should_retain_checkpoint(
    *,
    trigger: str,
    checkpoint_count: int,
    policy: CheckpointRetentionPolicy | None = None,
) -> bool:
    """Determine if a checkpoint should be retained based on policy."""
    p = policy or DEFAULT_RETENTION_POLICY

    if checkpoint_count >= p.max_checkpoints_per_working_staging:
        if trigger in ("pre_rebuild", "pre_rebuild_safety"):
            return p.retain_all_pre_rebuild
        if trigger in ("first_previewable_html", "first_previewable_state"):
            return p.retain_all_first_previewable
        if trigger in ("pre_approval", "pre_approval_freeze"):
            return p.retain_all_pre_approval
        return False

    return True


def checkpoint_reason_to_trigger(reason: CheckpointReason) -> str:
    """Convert a CheckpointReason to a legacy trigger string for compatibility."""
    mapping = {
        "pre_rebuild_safety": "pre_rebuild",
        "first_previewable_state": "first_previewable_html",
        "post_patch_milestone": "post_patch",
        "pre_approval_freeze": "pre_approval",
        "rollback_anchor": "manual",
        "operator_manual": "manual",
        "stagnation_recovery": "manual",
        "pressure_threshold": "pre_rebuild",
    }
    return mapping.get(reason.category, "manual")


def checkpoint_reason_to_payload(reason: CheckpointReason) -> dict[str, Any]:
    """Convert checkpoint reason to event payload."""
    return {
        "category": reason.category,
        "explanation": reason.explanation,
        "triggered_by": reason.triggered_by,
    }
