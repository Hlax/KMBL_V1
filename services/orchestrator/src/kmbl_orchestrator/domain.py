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


class RoleInvocationRecord(BaseModel):
    role_invocation_id: UUID
    graph_run_id: UUID
    thread_id: UUID
    role_type: Literal["planner", "generator", "evaluator"]
    provider: Literal["kiloclaw"] = "kiloclaw"
    provider_config_key: str
    input_payload_json: dict[str, Any]
    output_payload_json: dict[str, Any] | None = None
    status: Literal["queued", "running", "completed", "failed"]
    iteration_index: int = 0
    started_at: str = Field(default_factory=_utc_now_iso)
    ended_at: str | None = None


class GraphRunRecord(BaseModel):
    graph_run_id: UUID
    thread_id: UUID
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
    snapshot_payload_json: dict[str, Any] = Field(default_factory=dict)
    preview_url: str | None = None
    status: str = "review_ready"
    created_at: str = Field(default_factory=_utc_now_iso)
    approved_by: str | None = None
    approved_at: str | None = None
    rejected_by: str | None = None
    rejected_at: str | None = None
    rejection_reason: str | None = None


class PublicationSnapshotRecord(BaseModel):
    """publication_snapshot table — immutable canon after explicit publish (Pass D)."""

    publication_snapshot_id: UUID
    source_staging_snapshot_id: UUID
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
