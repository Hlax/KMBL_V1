"""Staging read routes — list, proposals, detail, static preview."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from kmbl_orchestrator.api.deps import get_repo
from kmbl_orchestrator.api.staging_models import (
    LinkedPublicationItem,
    LifecycleTimelineItem,
    StagingEvaluationDetail,
    StagingLineageSection,
    StagingListResponse,
    StagingSnapshotDetailResponse,
)
from kmbl_orchestrator.persistence.repository import Repository
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
    static_file_map_from_payload,
)

router = APIRouter()


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
    meta = p.get("metadata")
    preview_kind: str | None = None
    if isinstance(meta, dict):
        pk = meta.get("preview_kind")
        if pk in ("static", "external_url"):
            preview_kind = pk
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
        preview_kind=preview_kind,
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
            "Content-Security-Policy": (
                "default-src 'none'; img-src data: https:; font-src data:; "
                "style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                "connect-src 'self' https://unpkg.com https://cdn.jsdelivr.net"
            ),
            "Cache-Control": "private, no-store",
        },
    )


# MIME types for individual file serving
_FILE_MIME_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".glsl": "text/plain; charset=utf-8",
    ".wgsl": "text/plain; charset=utf-8",
    ".vert": "text/plain; charset=utf-8",
    ".frag": "text/plain; charset=utf-8",
    ".splat": "application/octet-stream",
    ".ply": "application/octet-stream",
}


@router.get("/orchestrator/staging/{staging_snapshot_id}/file/{file_path:path}")
def get_staging_file(
    staging_snapshot_id: str,
    file_path: str,
    repo: Repository = Depends(get_repo),
) -> Response:
    """
    Serve an individual file from a staging snapshot's ``static_frontend_file_v1`` artifacts.

    Supports .html, .css, .js, .json, .glsl, .wgsl, .vert, .frag, .splat, .ply with correct MIME types.
    Used by WebGL/shader previews that need to fetch config and shader files at runtime.
    """
    try:
        sid = UUID(staging_snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid staging_snapshot_id") from e
    rec = repo.get_staging_snapshot(sid)
    if rec is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    p = dict(rec.snapshot_payload_json)
    files = static_file_map_from_payload(p)

    # Normalize requested path and prevent directory traversal
    normalized_path = file_path.strip().replace("\\", "/")
    if not normalized_path.startswith("component/"):
        normalized_path = f"component/{normalized_path}"

    # Resolve ".." and "." segments to prevent path traversal attacks
    import posixpath
    resolved = posixpath.normpath(normalized_path)
    if not resolved.startswith("component/") or ".." in resolved:
        raise HTTPException(
            status_code=400,
            detail={"error_kind": "invalid_path", "reason": "path traversal not allowed"},
        )

    if resolved not in files:
        raise HTTPException(
            status_code=404,
            detail={"error_kind": "file_not_found", "path": resolved},
        )

    content = files[resolved]
    # Determine MIME type from extension
    ext = ""
    dot_idx = resolved.rfind(".")
    if dot_idx != -1:
        ext = resolved[dot_idx:]
    mime_type = _FILE_MIME_TYPES.get(ext, "text/plain; charset=utf-8")

    return Response(
        content=content.encode("utf-8"),
        media_type=mime_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
