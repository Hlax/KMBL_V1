"""Publication eligibility — persisted staging truth only (Pass D)."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.domain import StagingSnapshotRecord
from kmbl_orchestrator.staging.read_model import review_readiness_for_staging_record


class PublicationIneligible(Exception):
    """Staging row cannot be published — normalized ``reason`` for API mapping."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        self.message = message
        super().__init__(message)


def _payload_structurally_valid(payload: dict[str, Any]) -> bool:
    if not payload:
        return False
    if payload.get("version") == 1:
        return True
    ev = payload.get("evaluation")
    return isinstance(ev, dict)


def validate_publication_eligibility(staging: StagingSnapshotRecord) -> None:
    """
    Explicit checks before creating ``publication_snapshot``.

    Requires human approval: ``status == approved`` and a non-degenerate persisted payload.
    """
    if staging.status == "approved":
        pass
    elif staging.status == "review_ready":
        raise PublicationIneligible(
            "staging_not_approved",
            "staging_snapshot must be approved before publication",
        )
    else:
        raise PublicationIneligible(
            "staging_not_eligible",
            f"staging status {staging.status!r} is not publication-eligible",
        )

    rr = review_readiness_for_staging_record(staging)
    if not rr.get("approved"):
        raise PublicationIneligible(
            "review_not_satisfied",
            "staging_snapshot must be operator-approved for publication",
        )

    p = staging.snapshot_payload_json
    if not isinstance(p, dict):
        raise PublicationIneligible("invalid_payload", "snapshot_payload_json is not a dict")
    if not _payload_structurally_valid(p):
        raise PublicationIneligible(
            "invalid_payload",
            "persisted staging payload is missing required v1 fields",
        )

    # Check evaluator status - block publication of failed builds
    ev = p.get("evaluation")
    if isinstance(ev, dict):
        ev_status = ev.get("status")
        if ev_status in ("fail", "blocked"):
            raise PublicationIneligible(
                "evaluator_not_pass",
                f"cannot publish snapshot with evaluator status '{ev_status}'",
            )
