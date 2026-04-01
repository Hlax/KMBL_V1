"""Shared helpers for staging HTTP routes."""

from __future__ import annotations

from kmbl_orchestrator.api.staging_models import StagingMutationResponse
from kmbl_orchestrator.domain import StagingSnapshotRecord
from kmbl_orchestrator.staging.read_model import review_readiness_for_staging_record


def staging_mutation_response(rec: StagingSnapshotRecord) -> StagingMutationResponse:
    return StagingMutationResponse(
        staging_snapshot_id=str(rec.staging_snapshot_id),
        thread_id=str(rec.thread_id),
        status=rec.status,
        created_at=rec.created_at,
        preview_url=rec.preview_url,
        approved_by=rec.approved_by,
        approved_at=rec.approved_at,
        rejected_by=rec.rejected_by,
        rejected_at=rec.rejected_at,
        rejection_reason=rec.rejection_reason,
        review_readiness=review_readiness_for_staging_record(rec),
    )
