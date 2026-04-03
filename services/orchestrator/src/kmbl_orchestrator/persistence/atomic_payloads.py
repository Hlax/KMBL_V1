"""JSON payloads for Supabase Postgres RPC (atomic staging / working_staging writes)."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.domain import (
    PublicationSnapshotRecord,
    StagingCheckpointRecord,
    StagingSnapshotRecord,
    WorkingStagingRecord,
)


def staging_checkpoint_to_rpc_dict(rec: StagingCheckpointRecord) -> dict[str, Any]:
    d: dict[str, Any] = {
        "staging_checkpoint_id": str(rec.staging_checkpoint_id),
        "working_staging_id": str(rec.working_staging_id),
        "thread_id": str(rec.thread_id),
        "payload_snapshot_json": rec.payload_snapshot_json,
        "revision_at_checkpoint": rec.revision_at_checkpoint,
        "trigger": rec.trigger,
        "created_at": rec.created_at,
    }
    if rec.source_graph_run_id is not None:
        d["source_graph_run_id"] = str(rec.source_graph_run_id)
    if rec.reason_category is not None:
        d["reason_category"] = rec.reason_category
    if rec.reason_explanation is not None:
        d["reason_explanation"] = rec.reason_explanation
    return d


def working_staging_to_rpc_dict(rec: WorkingStagingRecord) -> dict[str, Any]:
    d: dict[str, Any] = {
        "working_staging_id": str(rec.working_staging_id),
        "thread_id": str(rec.thread_id),
        "payload_json": rec.payload_json,
        "last_update_mode": rec.last_update_mode,
        "revision": rec.revision,
        "status": rec.status,
        "created_at": rec.created_at,
        "updated_at": rec.updated_at,
        "stagnation_count": rec.stagnation_count,
        "last_evaluator_issue_count": rec.last_evaluator_issue_count,
        "last_revision_summary_json": rec.last_revision_summary_json,
    }
    if rec.identity_id is not None:
        d["identity_id"] = str(rec.identity_id)
    if rec.last_update_graph_run_id is not None:
        d["last_update_graph_run_id"] = str(rec.last_update_graph_run_id)
    if rec.last_update_build_candidate_id is not None:
        d["last_update_build_candidate_id"] = str(rec.last_update_build_candidate_id)
    if rec.current_checkpoint_id is not None:
        d["current_checkpoint_id"] = str(rec.current_checkpoint_id)
    if rec.last_rebuild_revision is not None:
        d["last_rebuild_revision"] = rec.last_rebuild_revision
    if rec.last_alignment_score is not None:
        d["last_alignment_score"] = rec.last_alignment_score
    return d


def staging_snapshot_to_rpc_dict(rec: StagingSnapshotRecord) -> dict[str, Any]:
    d: dict[str, Any] = {
        "staging_snapshot_id": str(rec.staging_snapshot_id),
        "thread_id": str(rec.thread_id),
        "build_candidate_id": str(rec.build_candidate_id),
        "snapshot_payload_json": rec.snapshot_payload_json,
        "status": rec.status,
        "created_at": rec.created_at,
        "marked_for_review": rec.marked_for_review,
        "review_tags": list(rec.review_tags),
    }
    if rec.graph_run_id is not None:
        d["graph_run_id"] = str(rec.graph_run_id)
    if rec.identity_id is not None:
        d["identity_id"] = str(rec.identity_id)
    if rec.prior_staging_snapshot_id is not None:
        d["prior_staging_snapshot_id"] = str(rec.prior_staging_snapshot_id)
    if rec.preview_url is not None:
        d["preview_url"] = rec.preview_url
    if rec.approved_by is not None:
        d["approved_by"] = rec.approved_by
    if rec.approved_at is not None:
        d["approved_at"] = rec.approved_at
    if rec.rejected_by is not None:
        d["rejected_by"] = rec.rejected_by
    if rec.rejected_at is not None:
        d["rejected_at"] = rec.rejected_at
    if rec.rejection_reason is not None:
        d["rejection_reason"] = rec.rejection_reason
    if rec.mark_reason is not None:
        d["mark_reason"] = rec.mark_reason
    if rec.user_rating is not None:
        d["user_rating"] = rec.user_rating
    if rec.user_feedback is not None:
        d["user_feedback"] = rec.user_feedback
    if rec.rated_at is not None:
        d["rated_at"] = rec.rated_at
    return d


def publication_snapshot_to_rpc_dict(rec: PublicationSnapshotRecord) -> dict[str, Any]:
    d: dict[str, Any] = {
        "publication_snapshot_id": str(rec.publication_snapshot_id),
        "source_staging_snapshot_id": str(rec.source_staging_snapshot_id),
        "payload_json": rec.payload_json,
        "visibility": rec.visibility,
        "published_at": rec.published_at,
    }
    if rec.thread_id is not None:
        d["thread_id"] = str(rec.thread_id)
    if rec.graph_run_id is not None:
        d["graph_run_id"] = str(rec.graph_run_id)
    if rec.identity_id is not None:
        d["identity_id"] = str(rec.identity_id)
    if rec.published_by is not None:
        d["published_by"] = rec.published_by
    if rec.parent_publication_snapshot_id is not None:
        d["parent_publication_snapshot_id"] = str(rec.parent_publication_snapshot_id)
    return d
