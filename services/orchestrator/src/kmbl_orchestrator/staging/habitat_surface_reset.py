"""Clear working staging for a true fresh-start while capturing fingerprints for validation."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.domain import WorkingStagingRecord
from kmbl_orchestrator.staging.duplicate_rejection import fingerprint_from_snapshot_payload


def fingerprint_working_staging_payload(payload_json: dict[str, Any]) -> str | None:
    """Fingerprint static HTML bundle in a working_staging.payload_json (snapshot-shaped)."""
    if not payload_json:
        return None
    return fingerprint_from_snapshot_payload(payload_json)


def clear_working_staging_surface(
    ws: WorkingStagingRecord,
    *,
    reason: str,
) -> tuple[WorkingStagingRecord, str | None]:
    """Reset mutable surface fields; returns (mutated ws, prior fingerprint or None)."""
    prior_fp = fingerprint_working_staging_payload(ws.payload_json)
    ws.payload_json = {}
    ws.revision = 0
    ws.last_rebuild_revision = None
    ws.stagnation_count = 0
    ws.last_evaluator_issue_count = 0
    ws.last_revision_summary_json = {}
    ws.last_alignment_score = None
    ws.last_update_mode = "init"
    ws.current_checkpoint_id = None
    ws.status = "draft"
    # working_staging_id / thread_id / identity_id unchanged
    _ = reason
    return ws, prior_fp
