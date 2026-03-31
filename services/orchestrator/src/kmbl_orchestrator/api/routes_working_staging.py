"""Working-staging routes — mutable staging area per thread."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from kmbl_orchestrator.api.deps import get_repo
from kmbl_orchestrator.domain import WorkingStagingRecord
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.staging.read_model import working_staging_read_model
from kmbl_orchestrator.staging.static_preview_assembly import (
    assemble_static_preview_html,
    resolve_static_preview_entry_path,
)
from kmbl_orchestrator.staging.static_preview_assembly_live import live_habitat_preview_surface
from kmbl_orchestrator.staging.working_staging_ops import (
    approve_working_staging,
    fresh_rebuild as ws_fresh_rebuild,
    rollback_to_checkpoint as ws_rollback_to_checkpoint,
    rollback_to_publication as ws_rollback_to_publication,
)

router = APIRouter()


# ── Models ─────────────────────────────────────────────────────────────────

class WorkingStagingResponse(BaseModel):
    working_staging_id: str
    thread_id: str
    identity_id: str | None = None
    revision: int
    status: str
    last_update_mode: str
    last_update_graph_run_id: str | None = None
    last_update_build_candidate_id: str | None = None
    current_checkpoint_id: str | None = None
    created_at: str
    updated_at: str
    payload_json: dict[str, Any] = Field(default_factory=dict)


class LiveWorkingStagingResponse(BaseModel):
    """Live evolving working staging — operator read model + preview surface hints (not a review snapshot)."""

    kind: Literal["live_working_staging"] = "live_working_staging"
    read_model: dict[str, Any]
    preview_surface: dict[str, Any]
    thread: dict[str, Any] | None = None


class WorkingStagingCheckpointItem(BaseModel):
    staging_checkpoint_id: str
    working_staging_id: str
    revision_at_checkpoint: int
    trigger: str
    source_graph_run_id: str | None = None
    created_at: str


class RollbackWorkingStagingBody(BaseModel):
    source: Literal["checkpoint", "publication", "fresh"]
    staging_checkpoint_id: UUID | None = None
    publication_snapshot_id: UUID | None = None


class ApproveWorkingStagingBody(BaseModel):
    approved_by: str | None = Field(
        default=None, description="Operator identifier."
    )


# ── Helpers ────────────────────────────────────────────────────────────────

def _ws_response(ws: WorkingStagingRecord) -> WorkingStagingResponse:
    return WorkingStagingResponse(
        working_staging_id=str(ws.working_staging_id),
        thread_id=str(ws.thread_id),
        identity_id=str(ws.identity_id) if ws.identity_id else None,
        revision=ws.revision,
        status=ws.status,
        last_update_mode=ws.last_update_mode,
        last_update_graph_run_id=str(ws.last_update_graph_run_id) if ws.last_update_graph_run_id else None,
        last_update_build_candidate_id=str(ws.last_update_build_candidate_id) if ws.last_update_build_candidate_id else None,
        current_checkpoint_id=str(ws.current_checkpoint_id) if ws.current_checkpoint_id else None,
        created_at=ws.created_at,
        updated_at=ws.updated_at,
        payload_json=dict(ws.payload_json),
    )


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get(
    "/orchestrator/working-staging/{thread_id}",
    response_model=WorkingStagingResponse,
)
def get_working_staging(
    thread_id: str,
    repo: Repository = Depends(get_repo),
) -> WorkingStagingResponse:
    """Current mutable working staging state for a thread."""
    try:
        tid = UUID(thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid thread_id") from e
    ws = repo.get_working_staging_for_thread(tid)
    if ws is None:
        raise HTTPException(status_code=404, detail="no working staging for this thread")
    return _ws_response(ws)


@router.get(
    "/orchestrator/working-staging/{thread_id}/live",
    response_model=LiveWorkingStagingResponse,
)
def get_working_staging_live(
    thread_id: str,
    repo: Repository = Depends(get_repo),
) -> LiveWorkingStagingResponse:
    """Compact live read model + preview surface hints for the mutable working staging (no snapshot row)."""
    try:
        tid = UUID(thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid thread_id") from e
    ws = repo.get_working_staging_for_thread(tid)
    if ws is None:
        raise HTTPException(status_code=404, detail="no working staging for this thread")
    rm = working_staging_read_model(ws)
    rm["last_alignment_score"] = ws.last_alignment_score
    rm["last_update_graph_run_id"] = (
        str(ws.last_update_graph_run_id) if ws.last_update_graph_run_id else None
    )
    rm["last_update_build_candidate_id"] = (
        str(ws.last_update_build_candidate_id) if ws.last_update_build_candidate_id else None
    )
    rm["current_checkpoint_id"] = str(ws.current_checkpoint_id) if ws.current_checkpoint_id else None
    preview_surface = live_habitat_preview_surface(dict(ws.payload_json))
    thread_info: dict[str, Any] | None = None
    tr = repo.get_thread(tid)
    if tr is not None:
        thread_info = {
            "thread_id": str(tr.thread_id),
            "identity_id": str(tr.identity_id) if tr.identity_id else None,
            "current_checkpoint_id": str(tr.current_checkpoint_id) if tr.current_checkpoint_id else None,
        }
    return LiveWorkingStagingResponse(
        read_model=rm,
        preview_surface=preview_surface,
        thread=thread_info,
    )


@router.get("/orchestrator/working-staging/{thread_id}/preview")
def get_working_staging_preview(
    thread_id: str,
    bundle_id: str | None = Query(None),
    repo: Repository = Depends(get_repo),
) -> Response:
    """Serve live static preview from the current working staging payload."""
    try:
        tid = UUID(thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid thread_id") from e
    ws = repo.get_working_staging_for_thread(tid)
    if ws is None:
        raise HTTPException(status_code=404, detail="no working staging for this thread")
    p = dict(ws.payload_json)
    entry, err = resolve_static_preview_entry_path(p, bundle_id=bundle_id)
    if err or not entry:
        raise HTTPException(
            status_code=404,
            detail={"error_kind": "static_preview_unavailable", "reason": err or "unknown"},
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


@router.get("/orchestrator/working-staging/{thread_id}/checkpoints")
def list_working_staging_checkpoints(
    thread_id: str,
    limit: int = Query(50, ge=1, le=200),
    repo: Repository = Depends(get_repo),
) -> dict[str, Any]:
    """List staging checkpoints for this thread's working staging."""
    try:
        tid = UUID(thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid thread_id") from e
    ws = repo.get_working_staging_for_thread(tid)
    if ws is None:
        raise HTTPException(status_code=404, detail="no working staging for this thread")
    checkpoints = repo.list_staging_checkpoints(ws.working_staging_id, limit=limit)
    items = [
        WorkingStagingCheckpointItem(
            staging_checkpoint_id=str(cp.staging_checkpoint_id),
            working_staging_id=str(cp.working_staging_id),
            revision_at_checkpoint=cp.revision_at_checkpoint,
            trigger=cp.trigger,
            source_graph_run_id=str(cp.source_graph_run_id) if cp.source_graph_run_id else None,
            created_at=cp.created_at,
        ).model_dump(mode="json")
        for cp in checkpoints
    ]
    return {"checkpoints": items, "count": len(items)}


@router.post(
    "/orchestrator/working-staging/{thread_id}/rollback",
    response_model=WorkingStagingResponse,
)
def rollback_working_staging(
    thread_id: str,
    body: RollbackWorkingStagingBody,
    repo: Repository = Depends(get_repo),
) -> WorkingStagingResponse:
    """Recover working staging from a checkpoint, publication, or fresh rebuild."""
    try:
        tid = UUID(thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid thread_id") from e
    ws = repo.get_working_staging_for_thread(tid)
    if ws is None:
        raise HTTPException(status_code=404, detail="no working staging for this thread")

    if body.source == "checkpoint":
        if body.staging_checkpoint_id is None:
            raise HTTPException(status_code=400, detail="staging_checkpoint_id required for checkpoint rollback")
        cp = repo.get_staging_checkpoint(body.staging_checkpoint_id)
        if cp is None:
            raise HTTPException(status_code=404, detail="staging_checkpoint not found")
        ws = ws_rollback_to_checkpoint(ws, cp)
    elif body.source == "publication":
        if body.publication_snapshot_id is None:
            raise HTTPException(status_code=400, detail="publication_snapshot_id required for publication rollback")
        pub = repo.get_publication_snapshot(body.publication_snapshot_id)
        if pub is None:
            raise HTTPException(status_code=404, detail="publication_snapshot not found")
        ws = ws_rollback_to_publication(ws, pub)
    else:
        ws = ws_fresh_rebuild(ws)

    repo.save_working_staging(ws)
    return _ws_response(ws)


@router.post(
    "/orchestrator/working-staging/{thread_id}/approve",
    response_model=WorkingStagingResponse,
)
def approve_working_staging_endpoint(
    thread_id: str,
    body: ApproveWorkingStagingBody = Body(default=ApproveWorkingStagingBody()),
    repo: Repository = Depends(get_repo),
) -> WorkingStagingResponse:
    """Freeze working staging into a publication snapshot."""
    try:
        tid = UUID(thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid thread_id") from e
    ws = repo.get_working_staging_for_thread(tid)
    if ws is None:
        raise HTTPException(status_code=404, detail="no working staging for this thread")
    if ws.status == "frozen":
        raise HTTPException(
            status_code=409,
            detail={"error_kind": "already_frozen", "message": "working staging is already frozen"},
        )
    if ws.revision == 0:
        raise HTTPException(
            status_code=409,
            detail={"error_kind": "empty_staging", "message": "cannot approve empty working staging"},
        )

    ws, pub, cp = approve_working_staging(ws, approved_by=body.approved_by or "operator")
    repo.save_staging_checkpoint(cp)
    repo.save_publication_snapshot(pub)
    repo.save_working_staging(ws)
    return _ws_response(ws)
