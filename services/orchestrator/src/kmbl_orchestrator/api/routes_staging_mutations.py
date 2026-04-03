"""Staging write routes — approve, reject, unapprove, rate."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException

from kmbl_orchestrator.api.deps import get_repo
from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.memory.ops import append_memory_event, record_operator_memory_from_staging_approval
from kmbl_orchestrator.api.staging_helpers import staging_mutation_response
from kmbl_orchestrator.api.staging_models import (
    ApproveStagingBody,
    RateStagingBody,
    RateStagingResponse,
    RejectStagingBody,
    StagingMutationResponse,
    UnapproveStagingBody,
)
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event

router = APIRouter()


@router.post(
    "/orchestrator/staging/{staging_snapshot_id}/approve",
    response_model=StagingMutationResponse,
)
def approve_staging_snapshot(
    staging_snapshot_id: str,
    body: ApproveStagingBody = Body(default=ApproveStagingBody()),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> StagingMutationResponse:
    """Transition ``review_ready`` → ``approved`` (explicit human approval; not a workflow engine)."""
    try:
        sid = UUID(staging_snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid staging_snapshot_id") from e
    rec = repo.get_staging_snapshot(sid)
    if rec is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    if rec.status == "approved":
        return staging_mutation_response(rec)
    if rec.status == "rejected":
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "approve_ineligible",
                "reason": "staging_rejected",
                "message": "cannot approve a rejected staging snapshot — create a new staging snapshot",
                "staging_status": rec.status,
            },
        )
    if rec.status != "review_ready":
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "approve_ineligible",
                "reason": "staging_not_review_ready",
                "message": f"cannot approve staging in status {rec.status!r}",
                "staging_status": rec.status,
            },
        )
    # Block approval when evaluator status is fail/blocked
    payload = rec.snapshot_payload_json
    if isinstance(payload, dict):
        ev = payload.get("evaluation")
        if isinstance(ev, dict):
            ev_status = ev.get("status")
            if ev_status in ("fail", "blocked"):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error_kind": "approve_ineligible",
                        "reason": "evaluator_not_pass",
                        "message": f"cannot approve snapshot with evaluator status '{ev_status}'",
                        "evaluator_status": ev_status,
                    },
                )
    updated = repo.update_staging_snapshot_status(
        sid, "approved", approved_by=body.approved_by
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    if updated.graph_run_id is not None:
        append_graph_run_event(
            repo,
            updated.graph_run_id,
            RunEventType.STAGING_SNAPSHOT_APPROVED,
            {
                "staging_snapshot_id": str(updated.staging_snapshot_id),
                "thread_id": str(updated.thread_id),
                "graph_run_id": str(updated.graph_run_id),
                "approved_by": body.approved_by,
            },
        )
    if updated.identity_id is not None:
        wt = record_operator_memory_from_staging_approval(
            repo,
            identity_id=updated.identity_id,
            graph_run_id=updated.graph_run_id,
            staging_snapshot_id=updated.staging_snapshot_id,
            settings=settings,
        )
        if wt is not None and updated.graph_run_id is not None:
            append_memory_event(
                repo,
                graph_run_id=updated.graph_run_id,
                thread_id=updated.thread_id,
                kind="updated",
                payload={
                    "memory_keys_written": wt.memory_keys_written,
                    "categories": wt.categories,
                    "phase": "operator_staging_approved",
                },
            )
    return staging_mutation_response(updated)


@router.post(
    "/orchestrator/staging/{staging_snapshot_id}/reject",
    response_model=StagingMutationResponse,
)
def reject_staging_snapshot(
    staging_snapshot_id: str,
    body: RejectStagingBody = Body(default=RejectStagingBody()),
    repo: Repository = Depends(get_repo),
) -> StagingMutationResponse:
    """
    Mark staging as ``rejected`` (terminal for this snapshot).

    Allowed from ``review_ready`` or ``approved`` when no publication exists for this staging id.
    """
    try:
        sid = UUID(staging_snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid staging_snapshot_id") from e
    rec = repo.get_staging_snapshot(sid)
    if rec is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    if rec.status == "rejected":
        return staging_mutation_response(rec)
    pubs = repo.list_publications_for_staging(sid)
    if pubs:
        latest = pubs[0]
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "reject_blocked_canon_exists",
                "message": "cannot reject — a publication snapshot already exists for this staging id",
                "staging_snapshot_id": str(sid),
                "publication_snapshot_id": str(latest.publication_snapshot_id),
            },
        )
    if rec.status not in ("review_ready", "approved"):
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "reject_ineligible",
                "message": f"cannot reject staging in status {rec.status!r}",
                "staging_status": rec.status,
            },
        )
    updated = repo.update_staging_snapshot_status(
        sid,
        "rejected",
        rejected_by=body.rejected_by,
        rejection_reason=body.rejection_reason,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    if updated.graph_run_id is not None:
        append_graph_run_event(
            repo,
            updated.graph_run_id,
            RunEventType.STAGING_SNAPSHOT_REJECTED,
            {
                "staging_snapshot_id": str(updated.staging_snapshot_id),
                "thread_id": str(updated.thread_id),
                "graph_run_id": str(updated.graph_run_id),
                "rejected_by": body.rejected_by,
                "rejection_reason": body.rejection_reason,
            },
        )
    return staging_mutation_response(updated)


@router.post(
    "/orchestrator/staging/{staging_snapshot_id}/unapprove",
    response_model=StagingMutationResponse,
)
def unapprove_staging_snapshot(
    staging_snapshot_id: str,
    body: UnapproveStagingBody = Body(default=UnapproveStagingBody()),
    repo: Repository = Depends(get_repo),
) -> StagingMutationResponse:
    """
    Transition ``approved`` → ``review_ready`` (withdraw approval).

    Only when no publication exists for this staging id.
    """
    try:
        sid = UUID(staging_snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid staging_snapshot_id") from e
    rec = repo.get_staging_snapshot(sid)
    if rec is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    pubs = repo.list_publications_for_staging(sid)
    if pubs:
        latest = pubs[0]
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "unapprove_blocked_canon_exists",
                "message": "cannot withdraw approval — a publication snapshot already exists",
                "staging_snapshot_id": str(sid),
                "publication_snapshot_id": str(latest.publication_snapshot_id),
            },
        )
    if rec.status != "approved":
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "unapprove_ineligible",
                "message": f"unapprove only applies to approved staging (current status {rec.status!r})",
                "staging_status": rec.status,
            },
        )
    updated = repo.update_staging_snapshot_status(sid, "review_ready")
    if updated is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    if updated.graph_run_id is not None:
        append_graph_run_event(
            repo,
            updated.graph_run_id,
            RunEventType.STAGING_SNAPSHOT_UNAPPROVED,
            {
                "staging_snapshot_id": str(updated.staging_snapshot_id),
                "thread_id": str(updated.thread_id),
                "graph_run_id": str(updated.graph_run_id),
                "unapproved_by": body.unapproved_by,
            },
        )
    return staging_mutation_response(updated)


@router.post(
    "/orchestrator/staging/{staging_snapshot_id}/rate",
    response_model=RateStagingResponse,
)
def rate_staging_snapshot(
    staging_snapshot_id: str,
    body: RateStagingBody,
    repo: Repository = Depends(get_repo),
) -> RateStagingResponse:
    """
    Rate a staging snapshot (1-5 scale).

    - 5: Excellent — exceeds expectations
    - 4: Good — meets expectations
    - 3: Acceptable — functional but could improve
    - 2: Poor — significant gaps, needs rework
    - 1: Reject — does not represent the identity

    Low ratings (1-2) can trigger re-iteration with feedback.
    """
    try:
        sid = UUID(staging_snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid staging_snapshot_id") from e
    rec = repo.get_staging_snapshot(sid)
    if rec is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")

    updated = repo.rate_staging_snapshot(sid, body.rating, body.feedback)
    if updated is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")

    if updated.graph_run_id is not None:
        append_graph_run_event(
            repo,
            updated.graph_run_id,
            RunEventType.STAGING_SNAPSHOT_RATED,
            {
                "staging_snapshot_id": str(updated.staging_snapshot_id),
                "thread_id": str(updated.thread_id),
                "graph_run_id": str(updated.graph_run_id),
                "user_rating": body.rating,
                "user_feedback": body.feedback,
            },
        )

    return RateStagingResponse(
        staging_snapshot_id=str(updated.staging_snapshot_id),
        thread_id=str(updated.thread_id),
        graph_run_id=str(updated.graph_run_id) if updated.graph_run_id else None,
        user_rating=updated.user_rating or body.rating,
        user_feedback=updated.user_feedback,
        rated_at=updated.rated_at or "",
        status=updated.status,
    )
