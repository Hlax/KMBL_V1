"""Apply staging_snapshot.status changes with consistent audit fields."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from kmbl_orchestrator.domain import StagingSnapshotRecord


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_staging_status_audit_patch(
    new_status: str,
    *,
    approved_by: str | None = None,
    rejected_by: str | None = None,
    rejection_reason: str | None = None,
) -> dict[str, Any]:
    """
    Column patch for ``staging_snapshot`` including explicit nulls for Supabase/PostgREST.

    Supported: ``approved``, ``review_ready``, ``rejected``.
    """
    patch: dict[str, Any] = {"status": new_status}
    if new_status == "approved":
        patch["approved_by"] = approved_by
        patch["approved_at"] = _utc_now_iso()
        patch["rejected_by"] = None
        patch["rejected_at"] = None
        patch["rejection_reason"] = None
    elif new_status == "review_ready":
        patch["approved_by"] = None
        patch["approved_at"] = None
        patch["rejected_by"] = None
        patch["rejected_at"] = None
        patch["rejection_reason"] = None
    elif new_status == "rejected":
        patch["approved_by"] = None
        patch["approved_at"] = None
        patch["rejected_at"] = _utc_now_iso()
        patch["rejected_by"] = rejected_by
        rr = (rejection_reason or "").strip()
        patch["rejection_reason"] = rr if rr else None
    return patch


def apply_staging_status_transition(
    cur: StagingSnapshotRecord,
    new_status: str,
    *,
    approved_by: str | None = None,
    rejected_by: str | None = None,
    rejection_reason: str | None = None,
) -> StagingSnapshotRecord:
    patch = build_staging_status_audit_patch(
        new_status,
        approved_by=approved_by,
        rejected_by=rejected_by,
        rejection_reason=rejection_reason,
    )
    keep = {k: v for k, v in patch.items() if k in StagingSnapshotRecord.model_fields}
    return cur.model_copy(update=keep)
