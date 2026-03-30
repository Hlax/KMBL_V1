"""Deterministic staging_snapshot payload from persisted rows only."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    BuildSpecRecord,
    EvaluationReportRecord,
    ThreadRecord,
)

# --- Explicit v1 contract (stable for review consumers; no raw provider blobs) ---


class StagingPayloadIdsV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    graph_run_id: str
    build_candidate_id: str
    evaluation_report_id: str
    identity_id: str | None = None
    build_spec_id: str | None = None


class StagingPayloadSummaryV1(BaseModel):
    """High-level build_spec summary (from persisted spec_json only)."""

    model_config = ConfigDict(extra="forbid")

    type: str | None = None
    title: str | None = None


class StagingPayloadEvaluationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    summary: str = ""
    issues: list[Any] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class StagingPayloadPreviewV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_url: str | None = None
    sandbox_ref: str | None = None


class StagingPayloadArtifactsV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_refs: list[Any] = Field(default_factory=list)


class StagingPayloadMetadataV1(BaseModel):
    """Non-UI working state slice persisted on the candidate (no raw KiloClaw envelope)."""

    model_config = ConfigDict(extra="forbid")

    working_state_patch: dict[str, Any] = Field(default_factory=dict)


class StagingSnapshotPayloadV1(BaseModel):
    """
    Versioned snapshot body stored in ``staging_snapshot.snapshot_payload_json``.

    Sections: ``ids``, ``summary``, ``evaluation``, ``preview``, ``artifacts``, ``metadata``.
    Built only from repository rows — no runtime-only fields.
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    ids: StagingPayloadIdsV1
    summary: StagingPayloadSummaryV1
    evaluation: StagingPayloadEvaluationV1
    preview: StagingPayloadPreviewV1
    artifacts: StagingPayloadArtifactsV1
    metadata: StagingPayloadMetadataV1


def build_staging_snapshot_payload(
    *,
    build_candidate: BuildCandidateRecord,
    evaluation_report: EvaluationReportRecord,
    thread: ThreadRecord,
    build_spec: BuildSpecRecord | None,
) -> dict[str, Any]:
    """
    Pure function: same persisted inputs → same JSON-serializable dict.

    No I/O, no generator calls, no raw ``raw_payload_json`` from roles.
    """
    sj: dict[str, Any] = build_spec.spec_json if build_spec is not None else {}
    spec_summary = StagingPayloadSummaryV1(
        type=sj.get("type") if isinstance(sj.get("type"), str) else None,
        title=sj.get("title") if isinstance(sj.get("title"), str) else None,
    )
    body = StagingSnapshotPayloadV1(
        ids=StagingPayloadIdsV1(
            thread_id=str(build_candidate.thread_id),
            graph_run_id=str(build_candidate.graph_run_id),
            build_candidate_id=str(build_candidate.build_candidate_id),
            evaluation_report_id=str(evaluation_report.evaluation_report_id),
            identity_id=str(thread.identity_id) if thread.identity_id is not None else None,
            build_spec_id=str(build_spec.build_spec_id) if build_spec is not None else None,
        ),
        summary=spec_summary,
        evaluation=StagingPayloadEvaluationV1(
            status=evaluation_report.status,
            summary=evaluation_report.summary or "",
            issues=list(evaluation_report.issues_json),
            metrics=dict(evaluation_report.metrics_json),
        ),
        preview=StagingPayloadPreviewV1(
            preview_url=build_candidate.preview_url,
            sandbox_ref=build_candidate.sandbox_ref,
        ),
        artifacts=StagingPayloadArtifactsV1(
            artifact_refs=list(build_candidate.artifact_refs_json),
        ),
        metadata=StagingPayloadMetadataV1(
            working_state_patch=dict(build_candidate.working_state_patch_json),
        ),
    )
    return body.model_dump(mode="json")
