"""Staging review routes — list, detail, approve, reject, unapprove, rate, proposals, static preview."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from kmbl_orchestrator.api.deps import get_repo
from kmbl_orchestrator.domain import StagingSnapshotRecord
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event
from kmbl_orchestrator.runtime.scenario_visibility import (
    gallery_strip_visibility_from_staging_payload,
    static_frontend_visibility_from_staging_payload,
)
from kmbl_orchestrator.staging.proposals_queue import (
    fetch_limit as proposals_fetch_limit,
    filter_proposals as filter_proposals_queue,
    normalize_blank as proposals_normalize_blank,
    parse_has_publication as proposals_parse_has_publication,
    parse_sort_mode as proposals_parse_sort_mode,
    sort_proposals_in_place,
    use_wide_pool as proposals_use_wide_pool,
    validate_review_action_state,
)
from kmbl_orchestrator.staging.read_model import (
    evaluation_summary_from_payload,
    evaluation_summary_section_from_payload,
    identity_hint_from_uuid,
    linked_publications_read_model,
    payload_version_from_payload,
    proposal_read_model,
    review_readiness_explanation_for_staging,
    review_readiness_for_staging_record,
    short_title_from_payload,
    staging_lineage_read_model,
    staging_lifecycle_timeline,
    staging_snapshot_list_item,
)
from kmbl_orchestrator.staging.review_action import derive_review_action_state
from kmbl_orchestrator.staging.static_preview_assembly import (
    assemble_static_preview_html,
    resolve_static_preview_entry_path,
)

router = APIRouter()


# ── Models ─────────────────────────────────────────────────────────────────

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


# ── Helpers ────────────────────────────────────────────────────────────────

def _staging_mutation_response(rec: StagingSnapshotRecord) -> StagingMutationResponse:
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


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("/orchestrator/staging", response_model=StagingListResponse)
def list_staging_snapshots(
    repo: Repository = Depends(get_repo),
    limit: int = Query(20, ge=1, le=200),
    status: str | None = Query(
        None,
        description="Filter by staging_snapshot.status (e.g. review_ready).",
    ),
    identity_id: str | None = Query(
        None,
        description="Filter by identity UUID.",
    ),
) -> StagingListResponse:
    """Query persisted staging rows for operator review — no runtime reconstruction."""
    id_u: UUID | None = None
    if identity_id is not None and identity_id.strip() != "":
        try:
            id_u = UUID(identity_id.strip())
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid identity_id") from e
    rows = repo.list_staging_snapshots(limit=limit, status=status, identity_id=id_u)
    snapshots = [staging_snapshot_list_item(r) for r in rows]
    return StagingListResponse(snapshots=snapshots, count=len(snapshots))


@router.get("/orchestrator/proposals")
def list_proposals(
    repo: Repository = Depends(get_repo),
    limit: int = Query(20, ge=1, le=200),
    identity_id: str | None = Query(
        None,
        description="Filter by identity UUID.",
    ),
    review_action_state: str | None = Query(
        None,
        description="Filter by derived review action state (Pass N).",
    ),
    staging_status: str | None = Query(
        None,
        description="Filter by staging_snapshot.status.",
    ),
    has_publication: str | None = Query(
        None,
        description="true = at least one publication row; false = none.",
    ),
    sort: str | None = Query(
        None,
        description="default = Pass J tiers; newest / oldest = by created_at only.",
    ),
) -> dict[str, Any]:
    """
    Review queue read model from persisted ``staging_snapshot`` rows (Pass J / N).

    Includes multiple staging statuses; each row gets ``review_action_state`` from stored
    status plus ``publication_snapshot`` counts — not a workflow engine.
    """
    id_u: UUID | None = None
    id_raw = proposals_normalize_blank(identity_id)
    if id_raw is not None:
        try:
            id_u = UUID(id_raw)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid identity_id") from e

    staging_f = proposals_normalize_blank(staging_status)
    try:
        ras_f = validate_review_action_state(review_action_state)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    has_pub_f = proposals_parse_has_publication(has_publication)
    sort_mode = proposals_parse_sort_mode(sort)
    wide = proposals_use_wide_pool(
        review_action_state=ras_f,
        has_publication=has_pub_f,
        sort_mode=sort_mode,
    )
    fetch_n = proposals_fetch_limit(limit=limit, wide=wide)

    rows = repo.list_staging_snapshots(
        limit=fetch_n,
        status=staging_f,
        identity_id=id_u,
    )
    sids = [r.staging_snapshot_id for r in rows]
    pub_counts = repo.publication_counts_for_staging_snapshot_ids(sids)
    proposals: list[dict[str, Any]] = []
    for r in rows:
        d = proposal_read_model(r)
        pc = pub_counts.get(r.staging_snapshot_id, 0)
        action, reason = derive_review_action_state(r, pc)
        d["linked_publication_count"] = pc
        d["review_action_state"] = action
        d["review_action_reason"] = reason
        proposals.append(d)

    proposals = filter_proposals_queue(
        proposals,
        review_action_state=ras_f,
        has_publication=has_pub_f,
    )
    sort_proposals_in_place(proposals, sort_mode=sort_mode)
    proposals = proposals[:limit]

    return {
        "proposals": proposals,
        "count": len(proposals),
        "basis": "persisted_rows_only",
    }


@router.post(
    "/orchestrator/staging/{staging_snapshot_id}/approve",
    response_model=StagingMutationResponse,
)
def approve_staging_snapshot(
    staging_snapshot_id: str,
    body: ApproveStagingBody = Body(default=ApproveStagingBody()),
    repo: Repository = Depends(get_repo),
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
        return _staging_mutation_response(rec)
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
    return _staging_mutation_response(updated)


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
        return _staging_mutation_response(rec)
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
    return _staging_mutation_response(updated)


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
    return _staging_mutation_response(updated)


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


@router.get(
    "/orchestrator/staging/{staging_snapshot_id}",
    response_model=StagingSnapshotDetailResponse,
)
def get_staging_snapshot(
    staging_snapshot_id: str,
    repo: Repository = Depends(get_repo),
) -> StagingSnapshotDetailResponse:
    """Return the persisted ``staging_snapshot`` row only — no runtime reconstruction."""
    try:
        sid = UUID(staging_snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid staging_snapshot_id") from e
    rec = repo.get_staging_snapshot(sid)
    if rec is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    pubs = repo.list_publications_for_staging(sid)
    p = dict(rec.snapshot_payload_json)
    timeline_raw = staging_lifecycle_timeline(rec, pubs)
    linked_raw = linked_publications_read_model(pubs)
    lineage_raw = staging_lineage_read_model(rec, p)
    eval_raw = evaluation_summary_section_from_payload(p)
    explain = review_readiness_explanation_for_staging(rec, p)
    gv = gallery_strip_visibility_from_staging_payload(p)
    fv = static_frontend_visibility_from_staging_payload(p)
    has_g = bool(gv.get("has_gallery_strip"))
    has_f = bool(fv.get("has_static_frontend"))
    if has_g and has_f:
        ck = "mixed"
    elif has_g:
        ck = "gallery_strip"
    elif has_f:
        ck = "static_frontend"
    else:
        ck = None
    return StagingSnapshotDetailResponse(
        staging_snapshot_id=str(rec.staging_snapshot_id),
        thread_id=str(rec.thread_id),
        build_candidate_id=str(rec.build_candidate_id),
        graph_run_id=str(rec.graph_run_id) if rec.graph_run_id else None,
        identity_id=str(rec.identity_id) if rec.identity_id else None,
        snapshot_payload_json=p,
        preview_url=rec.preview_url,
        status=rec.status,
        created_at=rec.created_at,
        approved_by=rec.approved_by,
        approved_at=rec.approved_at,
        rejected_by=rec.rejected_by,
        rejected_at=rec.rejected_at,
        rejection_reason=rec.rejection_reason,
        user_rating=rec.user_rating,
        user_feedback=rec.user_feedback,
        rated_at=rec.rated_at,
        evaluation_summary=evaluation_summary_from_payload(p),
        short_title=short_title_from_payload(p),
        identity_hint=identity_hint_from_uuid(rec.identity_id),
        review_readiness=review_readiness_for_staging_record(rec),
        review_readiness_explanation=explain,
        payload_version=payload_version_from_payload(p),
        lineage=StagingLineageSection(**lineage_raw),
        evaluation=StagingEvaluationDetail(**eval_raw),
        linked_publications=[LinkedPublicationItem(**x) for x in linked_raw],
        lifecycle_timeline=[LifecycleTimelineItem(**x) for x in timeline_raw],
        content_kind=ck,
        has_gallery_strip=has_g,
        gallery_strip_item_count=int(gv.get("gallery_strip_item_count") or 0),
        gallery_image_artifact_count=int(gv.get("gallery_image_artifact_count") or 0),
        gallery_items_with_artifact_key=int(gv.get("gallery_items_with_artifact_key") or 0),
        has_static_frontend=has_f,
        static_frontend_file_count=int(fv.get("static_frontend_file_count") or 0),
        static_frontend_bundle_count=int(fv.get("static_frontend_bundle_count") or 0),
        has_previewable_html=bool(fv.get("has_previewable_html")),
    )


@router.get("/orchestrator/staging/{staging_snapshot_id}/static-preview")
def get_staging_static_preview(
    staging_snapshot_id: str,
    bundle_id: str | None = Query(
        None,
        description="When set, preview the bundle with this slug (multiple bundles).",
    ),
    repo: Repository = Depends(get_repo),
) -> Response:
    """
    Serve one assembled HTML document for ``static_frontend_file_v1`` artifacts (trusted path).

    404 JSON when no previewable static bundle exists. No filesystem access — payload only.
    """
    try:
        sid = UUID(staging_snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid staging_snapshot_id") from e
    rec = repo.get_staging_snapshot(sid)
    if rec is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    p = dict(rec.snapshot_payload_json)
    entry, err = resolve_static_preview_entry_path(p, bundle_id=bundle_id)
    if err or not entry:
        raise HTTPException(
            status_code=404,
            detail={
                "error_kind": "static_preview_unavailable",
                "reason": err or "unknown",
            },
        )
    html, aerr = assemble_static_preview_html(p, entry_path=entry)
    if aerr or not html:
        raise HTTPException(
            status_code=404,
            detail={"error_kind": "static_preview_unavailable", "reason": aerr or "unknown"},
        )
    return Response(
        content=html.encode("utf-8"),
        media_type="text/html; charset=utf-8",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; img-src data: https:; font-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'",
            "Cache-Control": "private, no-store",
        },
    )
