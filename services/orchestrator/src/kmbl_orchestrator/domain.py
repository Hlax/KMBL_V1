"""Pydantic shapes aligned with docs/07_DATA_MODEL_AND_STACK_MAP.md (Python mirror of @kmbl/contracts)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ThreadRecord(BaseModel):
    """thread table — continuity container (docs/07 §1.4)."""

    thread_id: UUID
    identity_id: UUID | None = None
    thread_kind: str = "build"
    status: str = "active"
    current_checkpoint_id: UUID | None = None


class IdentitySourceRecord(BaseModel):
    """identity_source table — raw identity material (docs/07 §1.1)."""

    identity_source_id: UUID
    identity_id: UUID
    source_type: str
    source_uri: str | None = None
    raw_text: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now_iso)


class IdentityProfileRecord(BaseModel):
    """identity_profile table — working synthesis for an identity (docs/07 §1.2)."""

    identity_id: UUID
    profile_summary: str | None = None
    facets_json: dict[str, Any] = Field(default_factory=dict)
    open_questions_json: list[Any] = Field(default_factory=list)
    updated_at: str = Field(default_factory=_utc_now_iso)


class RoleInvocationRecord(BaseModel):
    role_invocation_id: UUID
    graph_run_id: UUID
    thread_id: UUID
    role_type: Literal["planner", "generator", "evaluator"]
    provider: Literal["kiloclaw"] = "kiloclaw"
    provider_config_key: str
    input_payload_json: dict[str, Any]
    output_payload_json: dict[str, Any] | None = None
    routing_metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        description="KMBL routing/budget decisions for this invocation (not model output).",
    )
    status: Literal["queued", "running", "completed", "failed"]
    iteration_index: int = 0
    started_at: str = Field(default_factory=_utc_now_iso)
    ended_at: str | None = None


class GraphRunRecord(BaseModel):
    graph_run_id: UUID
    thread_id: UUID
    identity_id: UUID | None = None
    trigger_type: Literal["prompt", "resume", "schedule", "system"]
    status: Literal["running", "paused", "completed", "failed"]
    started_at: str = Field(default_factory=_utc_now_iso)
    ended_at: str | None = None


class CheckpointRecord(BaseModel):
    checkpoint_id: UUID
    thread_id: UUID
    graph_run_id: UUID
    checkpoint_kind: Literal[
        "pre_role",
        "post_role",
        "post_step",
        "interrupt",
        "manual",
    ]
    state_json: dict[str, Any]
    context_compaction_json: dict[str, Any] | None = None
    created_at: str = Field(default_factory=_utc_now_iso)


class GraphRunEventRecord(BaseModel):
    """Append-only execution timeline row for a graph_run (local ops visibility)."""

    graph_run_event_id: UUID
    graph_run_id: UUID
    thread_id: UUID | None = None
    event_type: str
    payload_json: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now_iso)


class StagingSnapshotRecord(BaseModel):
    """staging_snapshot table — review surface; status flows e.g. review_ready → approved (Pass D)."""

    staging_snapshot_id: UUID
    thread_id: UUID
    build_candidate_id: UUID
    graph_run_id: UUID | None = None
    identity_id: UUID | None = None
    prior_staging_snapshot_id: UUID | None = None
    snapshot_payload_json: dict[str, Any] = Field(default_factory=dict)
    preview_url: str | None = None
    status: str = "review_ready"
    created_at: str = Field(default_factory=_utc_now_iso)
    approved_by: str | None = None
    approved_at: str | None = None
    rejected_by: str | None = None
    rejected_at: str | None = None
    # User rating (1-5 scale, None = not rated)
    user_rating: int | None = None
    user_feedback: str | None = None
    rated_at: str | None = None
    
    # Evaluator marks for review
    marked_for_review: bool = False
    mark_reason: str | None = None
    review_tags: list[str] = Field(default_factory=list)
    rejection_reason: str | None = None


class WorkingStagingRecord(BaseModel):
    """Mutable live surface for a thread/identity — amended by generator across runs."""

    working_staging_id: UUID
    thread_id: UUID
    identity_id: UUID | None = None

    payload_json: dict[str, Any] = Field(default_factory=dict)

    last_update_mode: Literal["patch", "rebuild", "init", "rollback"] = "init"
    last_update_graph_run_id: UUID | None = None
    last_update_build_candidate_id: UUID | None = None

    current_checkpoint_id: UUID | None = None

    revision: int = 0
    status: Literal["draft", "review_ready", "frozen"] = "draft"
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)

    last_rebuild_revision: int | None = Field(
        default=None,
        description="Revision number of the most recent rebuild (for pressure tracking).",
    )
    stagnation_count: int = Field(
        default=0,
        description="Count of iterations without evaluator improvement.",
    )
    last_evaluator_issue_count: int = Field(
        default=0,
        description="Issue count from most recent evaluation (for stagnation detection).",
    )
    last_revision_summary_json: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured summary of the most recent revision for audit/display.",
    )


class StagingCheckpointRecord(BaseModel):
    """Lightweight recovery point for working staging — distinct from graph CheckpointRecord."""

    staging_checkpoint_id: UUID
    working_staging_id: UUID
    thread_id: UUID

    payload_snapshot_json: dict[str, Any] = Field(default_factory=dict)
    revision_at_checkpoint: int = 0

    trigger: Literal[
        "pre_rebuild",
        "post_patch",
        "first_previewable_html",
        "pre_approval",
        "manual",
        "pressure_threshold",
        "stagnation_recovery",
        "post_patch_milestone",
    ] = "post_patch"

    source_graph_run_id: UUID | None = None
    created_at: str = Field(default_factory=_utc_now_iso)

    reason_category: str | None = Field(
        default=None,
        description="Structured checkpoint reason category (checkpoint_policy.CheckpointReason).",
    )
    reason_explanation: str | None = Field(
        default=None,
        description="Human-readable explanation for checkpoint creation.",
    )


class PublicationSnapshotRecord(BaseModel):
    """publication_snapshot table — immutable canon after explicit publish (Pass D)."""

    publication_snapshot_id: UUID
    source_staging_snapshot_id: UUID
    source_working_staging_id: UUID | None = None
    source_staging_checkpoint_id: UUID | None = None
    thread_id: UUID | None = None
    graph_run_id: UUID | None = None
    identity_id: UUID | None = None
    payload_json: dict[str, Any] = Field(default_factory=dict)
    visibility: Literal["private", "public"] = "private"
    published_by: str | None = None
    parent_publication_snapshot_id: UUID | None = None
    published_at: str = Field(default_factory=_utc_now_iso)


class BuildSpecRecord(BaseModel):
    build_spec_id: UUID
    thread_id: UUID
    graph_run_id: UUID
    planner_invocation_id: UUID
    spec_json: dict[str, Any]
    constraints_json: dict[str, Any] = Field(default_factory=dict)
    success_criteria_json: list[Any] = Field(default_factory=list)
    evaluation_targets_json: list[Any] = Field(default_factory=list)
    raw_payload_json: dict[str, Any] | None = None
    status: Literal["active", "superseded", "accepted"] = "active"
    created_at: str = Field(default_factory=_utc_now_iso)


class BuildCandidateRecord(BaseModel):
    build_candidate_id: UUID
    thread_id: UUID
    graph_run_id: UUID
    generator_invocation_id: UUID
    build_spec_id: UUID
    candidate_kind: Literal["habitat", "content", "full_app"]
    working_state_patch_json: dict[str, Any] = Field(default_factory=dict)
    artifact_refs_json: list[Any] = Field(default_factory=list)
    raw_payload_json: dict[str, Any] | None = None
    sandbox_ref: str | None = None
    preview_url: str | None = None
    status: Literal[
        "generated",
        "applied",
        "under_review",
        "superseded",
        "accepted",
    ] = "generated"
    created_at: str = Field(default_factory=_utc_now_iso)


class EvaluationReportRecord(BaseModel):
    evaluation_report_id: UUID
    thread_id: UUID
    graph_run_id: UUID
    evaluator_invocation_id: UUID
    build_candidate_id: UUID
    status: Literal["pass", "partial", "fail", "blocked"]
    summary: str = ""
    issues_json: list[Any] = Field(default_factory=list)
    metrics_json: dict[str, Any] = Field(default_factory=dict)
    artifacts_json: list[Any] = Field(default_factory=list)
    raw_payload_json: dict[str, Any] | None = None
    created_at: str = Field(default_factory=_utc_now_iso)


class AutonomousLoopRecord(BaseModel):
    """autonomous_loop table — tracks ongoing creative iteration for an identity."""

    loop_id: UUID
    identity_id: UUID
    identity_url: str

    # Loop state
    status: Literal["pending", "running", "paused", "completed", "failed"] = "pending"
    phase: Literal[
        "identity_fetch", "planning", "generating", "evaluating", "proposing", "idle"
    ] = "identity_fetch"

    # Iteration tracking
    iteration_count: int = 0
    max_iterations: int = 50

    # Current work references
    current_thread_id: UUID | None = None
    current_graph_run_id: UUID | None = None
    last_staging_snapshot_id: UUID | None = None
    last_evaluator_status: str | None = None
    last_evaluator_score: float | None = None

    # Planner exploration state
    exploration_directions: list[dict[str, Any]] = Field(default_factory=list)
    completed_directions: list[dict[str, Any]] = Field(default_factory=list)

    # Auto-publication settings
    auto_publish_threshold: float = 0.85
    proposed_staging_id: UUID | None = None
    proposed_at: str | None = None

    # Lock for cron
    locked_at: str | None = None
    locked_by: str | None = None

    # Metadata
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)
    completed_at: str | None = None

    # Stats
    total_staging_count: int = 0
    total_publication_count: int = 0
    best_rating: int | None = None
