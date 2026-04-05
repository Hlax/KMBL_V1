"""Opt-in maintenance endpoints (gated; operator-triggered)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.runtime.workspace_retention import (
    prune_stale_generator_workspaces,
    prune_stale_generator_workspaces_summary,
)

router = APIRouter(prefix="/orchestrator/maintenance", tags=["maintenance"])


class PruneGeneratorWorkspacesBody(BaseModel):
    """Request body for workspace prune. Default dry_run=true is intentional."""

    dry_run: bool = Field(default=True, description="If true, only list dirs that would be deleted.")
    protect_graph_run_ids: list[UUID] = Field(
        default_factory=list,
        description="Never delete these graph_run_id workspace folders (e.g. active runs).",
    )


@router.post("/prune-generator-workspaces")
def post_prune_generator_workspaces(
    body: PruneGeneratorWorkspacesBody,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """
    Run :func:`prune_stale_generator_workspaces` when HTTP maintenance is enabled.

    Requires ``KMBL_MAINTENANCE_PRUNE_HTTP_ENABLED=true``. Actual deletion also requires
    ``KMBL_GENERATOR_WORKSPACE_RETENTION_ENABLED=true`` and age policy — otherwise the prune
    function no-ops. When ``ORCHESTRATOR_API_KEY`` is set, POST must include it (middleware).
    """
    if not bool(getattr(settings, "kmbl_maintenance_prune_http_enabled", False)):
        raise HTTPException(
            status_code=403,
            detail={
                "error_kind": "maintenance_endpoint_disabled",
                "message": "Set KMBL_MAINTENANCE_PRUNE_HTTP_ENABLED=true to enable this endpoint.",
            },
        )
    protect = frozenset(body.protect_graph_run_ids) if body.protect_graph_run_ids else None
    result = prune_stale_generator_workspaces(
        settings,
        dry_run=body.dry_run,
        protect_graph_run_ids=protect,
    )
    return {
        "ok": True,
        "dry_run": body.dry_run,
        "retention_enabled": bool(getattr(settings, "kmbl_generator_workspace_retention_enabled", False)),
        "min_age_days": float(getattr(settings, "kmbl_generator_workspace_retention_min_age_days", 14.0)),
        **prune_stale_generator_workspaces_summary(result),
        "skipped_reasons_sample": dict(list(result.skipped_reasons.items())[:24]),
    }
