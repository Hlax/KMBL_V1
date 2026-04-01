"""Pydantic models for staging review API (extracted from routes_staging)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LinkedPublicationItem(BaseModel):
    """Publication snapshot linked from staging (Pass G)."""

    publication_snapshot_id: str
    published_at: str
    visibility: str


class LifecycleTimelineItem(BaseModel):
    """Derived lifecycle step from persisted rows only (Pass F)."""

    kind: str
    label: str
    at: str | None = None
    ref_publication_snapshot_id: str | None = None


class StagingLineageSection(BaseModel):
    """Provenance from persisted row + ``snapshot_payload_json.ids`` (Pass G)."""

    thread_id: str
    graph_run_id: str | None = None
    build_candidate_id: str
    evaluation_report_id: str | None = None
    identity_id: str | None = None
    prior_staging_snapshot_id: str | None = Field(
        default=None,
        description="Previous staging snapshot on the same thread (amend chain).",
    )


class StagingEvaluationDetail(BaseModel):
    """Evaluator output slice from persisted payload (Pass G) — not live runtime."""

    present: bool = False
    status: str | None = None
    summary: str = ""
    issue_count: int = 0
    artifact_count: int = 0
    metrics_key_count: int = 0
    metrics_preview: dict[str, Any] = Field(default_factory=dict)


class StagingSnapshotDetailResponse(BaseModel):
    """
    Persisted ``staging_snapshot`` row plus derived read-model fields (Pass C).

    Source of truth is the stored row and ``snapshot_payload_json`` only — no runtime or
    checkpoint reconstruction.
    """

    staging_snapshot_id: str
    thread_id: str
    build_candidate_id: str
    graph_run_id: str | None = None
    identity_id: str | None = None
    snapshot_payload_json: dict[str, Any] = Field(
        default_factory=dict,
        description="V1 payload sections: ids, summary, evaluation, preview, artifacts, metadata.",
    )
    preview_url: str | None = None
    status: str
    created_at: str
    approved_by: str | None = None
    approved_at: str | None = None
    rejected_by: str | None = None
    rejected_at: str | None = None
    rejection_reason: str | None = None
    user_rating: int | None = None
    user_feedback: str | None = None
    rated_at: str | None = None
    evaluation_summary: str = ""
    short_title: str | None = None
    identity_hint: str | None = None
    review_readiness: dict[str, Any] = Field(default_factory=dict)
    review_readiness_explanation: str = Field(
        default="",
        description="Derived operator-facing text from persisted status + payload (Pass G).",
    )
    payload_version: int | None = Field(
        default=None,
        description="From ``snapshot_payload_json.version`` when present (e.g. 1).",
    )
    lineage: StagingLineageSection = Field(
        description="Structured provenance — same ids as row + payload.ids where present.",
    )
    evaluation: StagingEvaluationDetail = Field(
        default_factory=StagingEvaluationDetail,
        description="Persisted evaluator output from snapshot payload (Pass G).",
    )
    linked_publications: list[LinkedPublicationItem] = Field(default_factory=list)
    lifecycle_timeline: list[LifecycleTimelineItem] = Field(default_factory=list)
    content_kind: str | None = Field(
        default=None,
        description="Derived: gallery_strip, static_frontend, mixed, or null.",
    )
    has_gallery_strip: bool = False
    gallery_strip_item_count: int = 0
    gallery_image_artifact_count: int = 0
    gallery_items_with_artifact_key: int = 0
    has_static_frontend: bool = False
    static_frontend_file_count: int = 0
    static_frontend_bundle_count: int = 0
    has_previewable_html: bool = False
    preview_kind: str | None = Field(
        default=None,
        description="From snapshot_payload_json.metadata.preview_kind: static | external_url.",
    )


class ApproveStagingBody(BaseModel):
    approved_by: str | None = Field(
        default=None,
        description="Operator identifier (audit / timeline only).",
    )


class RejectStagingBody(BaseModel):
    rejected_by: str | None = Field(
        default=None,
        description="Operator identifier (audit only).",
    )
    rejection_reason: str | None = Field(
        default=None,
        max_length=4000,
        description="Optional short note stored on the staging row.",
    )


class UnapproveStagingBody(BaseModel):
    unapproved_by: str | None = Field(
        default=None,
        description="Optional operator id recorded in the graph_run event payload only.",
    )


class StagingMutationResponse(BaseModel):
    """Shared shape for approve / reject / unapprove responses."""

    staging_snapshot_id: str
    thread_id: str
    status: str
    created_at: str
    preview_url: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    rejected_by: str | None = None
    rejected_at: str | None = None
    rejection_reason: str | None = None
    review_readiness: dict[str, Any] = Field(default_factory=dict)


ApproveStagingResponse = StagingMutationResponse


class StagingListResponse(BaseModel):
    """GET /orchestrator/staging — compact rows only (no full ``snapshot_payload_json``)."""

    snapshots: list[dict[str, Any]]
    count: int
    basis: Literal["persisted_rows_only"] = "persisted_rows_only"


class RateStagingBody(BaseModel):
    """Body for rating a staging snapshot."""

    rating: int = Field(
        ...,
        ge=1,
        le=5,
        description="User rating 1-5 (1=reject, 5=excellent)",
    )
    feedback: str | None = Field(
        default=None,
        description="Optional feedback explaining the rating",
    )


class RateStagingResponse(BaseModel):
    staging_snapshot_id: str
    thread_id: str
    graph_run_id: str | None
    user_rating: int
    user_feedback: str | None
    rated_at: str
    status: str
