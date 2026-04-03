"""Publication routes — create, list, get publications."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from kmbl_orchestrator.api.deps import get_repo
from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.memory.ops import append_memory_event, record_operator_memory_from_publication
from pydantic import BaseModel, Field

from kmbl_orchestrator.domain import PublicationSnapshotRecord
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.publication.eligibility import (
    PublicationIneligible,
    validate_publication_eligibility,
)
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event

router = APIRouter()


# ── Models ─────────────────────────────────────────────────────────────────

class CreatePublicationBody(BaseModel):
    staging_snapshot_id: UUID
    visibility: Literal["private", "public"] = "private"
    published_by: str | None = Field(
        default=None,
        description="Operator identifier recorded on the publication row.",
    )


class CreatePublicationResponse(BaseModel):
    publication_snapshot_id: str
    source_staging_snapshot_id: str
    identity_id: str | None
    visibility: str
    published_at: str
    published_by: str | None = None
    status: Literal["published"] = "published"


class PublicationSnapshotListItem(BaseModel):
    publication_snapshot_id: str
    source_staging_snapshot_id: str
    identity_id: str | None = None
    visibility: str
    published_at: str
    published_by: str | None = None


class PublicationListResponse(BaseModel):
    publications: list[PublicationSnapshotListItem]
    count: int
    basis: Literal["persisted_rows_only"] = "persisted_rows_only"


class PublicationLineageSection(BaseModel):
    """Grouped provenance for canon snapshot (Pass G)."""

    source_staging_snapshot_id: str
    parent_publication_snapshot_id: str | None = None
    identity_id: str | None = None
    thread_id: str | None = None
    graph_run_id: str | None = None


class PublicationSnapshotDetailResponse(BaseModel):
    """Immutable persisted publication (canon) — no runtime reconstruction."""

    publication_snapshot_id: str
    source_staging_snapshot_id: str
    thread_id: str | None = None
    graph_run_id: str | None = None
    identity_id: str | None = None
    payload_json: dict[str, Any] = Field(default_factory=dict)
    visibility: str
    published_by: str | None = None
    parent_publication_snapshot_id: str | None = None
    published_at: str
    publication_lineage: PublicationLineageSection = Field(
        description="Mirrors key lineage fields for scanning (Pass G).",
    )


# ── Helpers ────────────────────────────────────────────────────────────────

def _publication_list_item(rec: PublicationSnapshotRecord) -> PublicationSnapshotListItem:
    return PublicationSnapshotListItem(
        publication_snapshot_id=str(rec.publication_snapshot_id),
        source_staging_snapshot_id=str(rec.source_staging_snapshot_id),
        identity_id=str(rec.identity_id) if rec.identity_id else None,
        visibility=rec.visibility,
        published_at=rec.published_at,
        published_by=rec.published_by,
    )


def _publication_detail(rec: PublicationSnapshotRecord) -> PublicationSnapshotDetailResponse:
    lineage = PublicationLineageSection(
        source_staging_snapshot_id=str(rec.source_staging_snapshot_id),
        parent_publication_snapshot_id=str(rec.parent_publication_snapshot_id)
        if rec.parent_publication_snapshot_id
        else None,
        identity_id=str(rec.identity_id) if rec.identity_id else None,
        thread_id=str(rec.thread_id) if rec.thread_id else None,
        graph_run_id=str(rec.graph_run_id) if rec.graph_run_id else None,
    )
    return PublicationSnapshotDetailResponse(
        publication_snapshot_id=str(rec.publication_snapshot_id),
        source_staging_snapshot_id=str(rec.source_staging_snapshot_id),
        thread_id=str(rec.thread_id) if rec.thread_id else None,
        graph_run_id=str(rec.graph_run_id) if rec.graph_run_id else None,
        identity_id=str(rec.identity_id) if rec.identity_id else None,
        payload_json=dict(rec.payload_json),
        visibility=rec.visibility,
        published_by=rec.published_by,
        parent_publication_snapshot_id=str(rec.parent_publication_snapshot_id)
        if rec.parent_publication_snapshot_id
        else None,
        published_at=rec.published_at,
        publication_lineage=lineage,
    )


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get(
    "/orchestrator/publication/current",
    response_model=PublicationSnapshotDetailResponse,
)
def get_current_publication(
    repo: Repository = Depends(get_repo),
    identity_id: str | None = Query(
        None,
        description="When set, latest publication for this identity; else latest overall.",
    ),
) -> PublicationSnapshotDetailResponse:
    id_u: UUID | None = None
    if identity_id is not None and identity_id.strip() != "":
        try:
            id_u = UUID(identity_id.strip())
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid identity_id") from e
    cur = repo.get_latest_publication_snapshot(identity_id=id_u)
    if cur is None:
        raise HTTPException(status_code=404, detail="no publication_snapshot found")
    return _publication_detail(cur)


@router.get("/orchestrator/publication", response_model=PublicationListResponse)
def list_publications(
    repo: Repository = Depends(get_repo),
    limit: int = Query(20, ge=1, le=200),
    identity_id: str | None = Query(None, description="Filter by identity UUID."),
    visibility: str | None = Query(
        None,
        description="Filter by visibility (private or public).",
    ),
) -> PublicationListResponse:
    id_u: UUID | None = None
    if identity_id is not None and identity_id.strip() != "":
        try:
            id_u = UUID(identity_id.strip())
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid identity_id") from e
    vis: str | None = None
    if visibility is not None and visibility.strip() != "":
        v = visibility.strip().lower()
        if v not in ("private", "public"):
            raise HTTPException(status_code=400, detail="invalid visibility")
        vis = v
    rows = repo.list_publication_snapshots(
        limit=limit, identity_id=id_u, visibility=vis
    )
    items = [_publication_list_item(r) for r in rows]
    return PublicationListResponse(publications=items, count=len(items))


@router.post(
    "/orchestrator/publication",
    response_model=CreatePublicationResponse,
)
def create_publication(
    body: Annotated[CreatePublicationBody, Body()],
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> CreatePublicationResponse:
    """Create immutable ``publication_snapshot`` from an **approved** staging row only."""
    staging = repo.get_staging_snapshot(body.staging_snapshot_id)
    if staging is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    existing = repo.list_publications_for_staging(staging.staging_snapshot_id)
    if existing:
        latest = existing[0]
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "publication_already_exists_for_staging",
                "message": "a publication snapshot already exists for this staging snapshot",
                "staging_snapshot_id": str(staging.staging_snapshot_id),
                "publication_snapshot_id": str(latest.publication_snapshot_id),
            },
        )
    try:
        validate_publication_eligibility(staging)
    except PublicationIneligible as e:
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "publication_ineligible",
                "reason": e.reason,
                "message": e.message,
            },
        ) from e

    parent = repo.get_latest_publication_snapshot(identity_id=staging.identity_id)
    pub_id = uuid4()
    published_at = datetime.now(timezone.utc).isoformat()
    snap = PublicationSnapshotRecord(
        publication_snapshot_id=pub_id,
        source_staging_snapshot_id=staging.staging_snapshot_id,
        thread_id=staging.thread_id,
        graph_run_id=staging.graph_run_id,
        identity_id=staging.identity_id,
        payload_json=copy.deepcopy(staging.snapshot_payload_json),
        visibility=body.visibility,
        published_by=body.published_by,
        parent_publication_snapshot_id=parent.publication_snapshot_id if parent else None,
        published_at=published_at,
    )
    repo.save_publication_snapshot(snap)
    if staging.graph_run_id is not None:
        append_graph_run_event(
            repo,
            staging.graph_run_id,
            RunEventType.PUBLICATION_SNAPSHOT_CREATED,
            {
                "publication_snapshot_id": str(pub_id),
                "source_staging_snapshot_id": str(staging.staging_snapshot_id),
                "identity_id": str(staging.identity_id) if staging.identity_id else None,
                "visibility": body.visibility,
                "published_by": body.published_by,
            },
        )
    if staging.identity_id is not None:
        wt = record_operator_memory_from_publication(
            repo,
            identity_id=staging.identity_id,
            graph_run_id=staging.graph_run_id,
            staging_snapshot_id=staging.staging_snapshot_id,
            settings=settings,
        )
        if wt is not None and staging.graph_run_id is not None:
            append_memory_event(
                repo,
                graph_run_id=staging.graph_run_id,
                thread_id=staging.thread_id,
                kind="updated",
                payload={
                    "memory_keys_written": wt.memory_keys_written,
                    "categories": wt.categories,
                    "phase": "operator_publication",
                },
            )
    return CreatePublicationResponse(
        publication_snapshot_id=str(pub_id),
        source_staging_snapshot_id=str(staging.staging_snapshot_id),
        identity_id=str(staging.identity_id) if staging.identity_id else None,
        visibility=body.visibility,
        published_at=published_at,
        published_by=body.published_by,
    )


@router.get(
    "/orchestrator/publication/{publication_snapshot_id}",
    response_model=PublicationSnapshotDetailResponse,
)
def get_publication_snapshot(
    publication_snapshot_id: str,
    repo: Repository = Depends(get_repo),
) -> PublicationSnapshotDetailResponse:
    try:
        pid = UUID(publication_snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid publication_snapshot_id") from e
    rec = repo.get_publication_snapshot(pid)
    if rec is None:
        raise HTTPException(status_code=404, detail="publication_snapshot not found")
    return _publication_detail(rec)
