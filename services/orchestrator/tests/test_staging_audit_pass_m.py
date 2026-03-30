"""Pass M — proposals read model exposes persisted approval audit fields."""

from __future__ import annotations

from uuid import uuid4

from kmbl_orchestrator.domain import StagingSnapshotRecord
from kmbl_orchestrator.staging.read_model import proposal_read_model


def test_proposal_read_model_includes_approved_audit_columns() -> None:
    sid = uuid4()
    tid = uuid4()
    bc = uuid4()
    rec = StagingSnapshotRecord(
        staging_snapshot_id=sid,
        thread_id=tid,
        build_candidate_id=bc,
        snapshot_payload_json={},
        status="approved",
        approved_by="operator-a",
        approved_at="2026-03-29T12:00:00+00:00",
    )
    d = proposal_read_model(rec)
    assert d["approved_by"] == "operator-a"
    assert d["approved_at"] == "2026-03-29T12:00:00+00:00"


def test_proposal_read_model_null_approval_when_not_set() -> None:
    sid = uuid4()
    tid = uuid4()
    bc = uuid4()
    rec = StagingSnapshotRecord(
        staging_snapshot_id=sid,
        thread_id=tid,
        build_candidate_id=bc,
        snapshot_payload_json={},
        status="review_ready",
    )
    d = proposal_read_model(rec)
    assert d.get("approved_by") is None
    assert d.get("approved_at") is None
