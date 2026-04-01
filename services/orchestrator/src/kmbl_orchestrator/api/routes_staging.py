"""Staging review routes — list, detail, approve, reject, unapprove, rate, static preview.

Composed from :mod:`routes_staging_query` (reads) and :mod:`routes_staging_mutations` (writes).
Models live in :mod:`staging_models`.
"""

from __future__ import annotations

from fastapi import APIRouter

from kmbl_orchestrator.api.routes_staging_mutations import router as _mutations_router
from kmbl_orchestrator.api.routes_staging_query import router as _query_router
from kmbl_orchestrator.api.staging_models import (
    ApproveStagingBody,
    ApproveStagingResponse,
    LinkedPublicationItem,
    LifecycleTimelineItem,
    RateStagingBody,
    RateStagingResponse,
    RejectStagingBody,
    StagingEvaluationDetail,
    StagingLineageSection,
    StagingListResponse,
    StagingMutationResponse,
    StagingSnapshotDetailResponse,
    UnapproveStagingBody,
)

router = APIRouter()
router.include_router(_query_router)
router.include_router(_mutations_router)

__all__ = [
    "ApproveStagingBody",
    "ApproveStagingResponse",
    "LinkedPublicationItem",
    "LifecycleTimelineItem",
    "RateStagingBody",
    "RateStagingResponse",
    "RejectStagingBody",
    "StagingEvaluationDetail",
    "StagingLineageSection",
    "StagingListResponse",
    "StagingMutationResponse",
    "StagingSnapshotDetailResponse",
    "UnapproveStagingBody",
    "router",
]
