"""Identity routes — CRUD for identity sources and profiles."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from kmbl_orchestrator.api.deps import get_repo
from kmbl_orchestrator.domain import IdentityProfileRecord, IdentitySourceRecord
from kmbl_orchestrator.persistence.repository import Repository

router = APIRouter()


class CreateIdentitySourceBody(BaseModel):
    identity_id: UUID
    source_type: str
    source_uri: str | None = None
    raw_text: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class UpsertIdentityProfileBody(BaseModel):
    profile_summary: str | None = None
    facets_json: dict[str, Any] = Field(default_factory=dict)
    open_questions_json: list[Any] = Field(default_factory=list)


@router.post("/orchestrator/identity/sources")
def create_identity_source_endpoint(
    body: CreateIdentitySourceBody,
    repo: Repository = Depends(get_repo),
) -> dict[str, str]:
    """Persist one identity_source row (minimal spine — docs/07 §1.1)."""
    rid = uuid4()
    rec = IdentitySourceRecord(
        identity_source_id=rid,
        identity_id=body.identity_id,
        source_type=body.source_type,
        source_uri=body.source_uri,
        raw_text=body.raw_text,
        metadata_json=body.metadata_json,
    )
    repo.create_identity_source(rec)
    return {"identity_source_id": str(rid), "identity_id": str(body.identity_id)}


@router.get("/orchestrator/identity/{identity_id}/profile")
def get_identity_profile_endpoint(
    identity_id: str,
    repo: Repository = Depends(get_repo),
) -> dict[str, Any]:
    try:
        uid = UUID(identity_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid identity_id") from e
    p = repo.get_identity_profile(uid)
    if p is None:
        return {"identity_id": identity_id, "profile": None}
    return {"identity_id": str(p.identity_id), "profile": p.model_dump(mode="json")}


@router.put("/orchestrator/identity/{identity_id}/profile")
def upsert_identity_profile_endpoint(
    identity_id: str,
    body: UpsertIdentityProfileBody,
    repo: Repository = Depends(get_repo),
) -> dict[str, Any]:
    try:
        uid = UUID(identity_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid identity_id") from e
    rec = IdentityProfileRecord(
        identity_id=uid,
        profile_summary=body.profile_summary,
        facets_json=body.facets_json,
        open_questions_json=body.open_questions_json,
    )
    repo.upsert_identity_profile(rec)
    return {"ok": True, "identity_id": str(uid)}


@router.get("/orchestrator/identity/{identity_id}/sources")
def list_identity_sources_endpoint(
    identity_id: str,
    repo: Repository = Depends(get_repo),
) -> dict[str, Any]:
    try:
        uid = UUID(identity_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid identity_id") from e
    rows = repo.list_identity_sources(uid)
    return {
        "identity_id": str(uid),
        "sources": [r.model_dump(mode="json") for r in rows],
        "count": len(rows),
    }
