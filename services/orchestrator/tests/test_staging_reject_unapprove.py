"""Reject / unapprove staging — status transitions and canon guards."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from kmbl_orchestrator.api.main import app, get_repo
from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.domain import (
    PublicationSnapshotRecord,
    StagingSnapshotRecord,
    ThreadRecord,
)
from kmbl_orchestrator.persistence.factory import reset_repository_singleton_for_tests
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.runtime.run_events import RunEventType


@pytest.fixture
def clear_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()


def _v1_payload() -> dict:
    return {
        "version": 1,
        "ids": {
            "thread_id": str(uuid4()),
            "graph_run_id": str(uuid4()),
            "build_candidate_id": str(uuid4()),
            "evaluation_report_id": str(uuid4()),
            "identity_id": None,
            "build_spec_id": str(uuid4()),
        },
        "summary": {"type": "app", "title": "T"},
        "evaluation": {"status": "pass", "summary": "ok", "issues": [], "metrics": {}},
        "preview": {"preview_url": "https://p.example", "sandbox_ref": None},
        "artifacts": {"artifact_refs": []},
        "metadata": {"working_state_patch": {}},
    }


def _seed_review_ready(
    repo: InMemoryRepository, *, gid: UUID | None = None
) -> tuple[UUID, StagingSnapshotRecord]:
    tid = uuid4()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    sid = uuid4()
    rec = StagingSnapshotRecord(
        staging_snapshot_id=sid,
        thread_id=tid,
        build_candidate_id=uuid4(),
        graph_run_id=gid,
        snapshot_payload_json=_v1_payload(),
        preview_url="https://pv.example",
        status="review_ready",
        created_at="2026-03-29T12:00:00+00:00",
    )
    repo.save_staging_snapshot(rec)
    return sid, rec


def test_reject_review_ready_idempotent(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    gid = uuid4()
    sid, _ = _seed_review_ready(repo, gid=gid)

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        c = TestClient(app)
        r = c.post(
            f"/orchestrator/staging/{sid}/reject",
            json={"rejected_by": "op-r", "rejection_reason": "no go"},
        )
        assert r.status_code == 200
        b = r.json()
        assert b["status"] == "rejected"
        assert b["review_readiness"]["rejected"] is True
        assert b.get("rejection_reason") == "no go"
        r2 = c.post(f"/orchestrator/staging/{sid}/reject", json={})
        assert r2.status_code == 200
        assert r2.json()["status"] == "rejected"
        evs = repo.list_graph_run_events(gid, limit=50)
        rej = [e for e in evs if e.event_type == RunEventType.STAGING_SNAPSHOT_REJECTED]
        assert len(rej) == 1
    finally:
        app.dependency_overrides.clear()


def test_reject_blocked_when_canon_exists(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    gid = uuid4()
    sid, rec = _seed_review_ready(repo, gid=gid)
    pub = PublicationSnapshotRecord(
        publication_snapshot_id=uuid4(),
        source_staging_snapshot_id=sid,
        payload_json=deepcopy(rec.snapshot_payload_json),
        visibility="private",
        published_at="2026-03-29T13:00:00+00:00",
    )
    repo.save_publication_snapshot(pub)

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        c = TestClient(app)
        r = c.post(f"/orchestrator/staging/{sid}/reject", json={})
        assert r.status_code == 409
        assert r.json()["detail"]["error_kind"] == "reject_blocked_canon_exists"
    finally:
        app.dependency_overrides.clear()


def test_unapprove_approved_to_review_ready(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    gid = uuid4()
    sid, _ = _seed_review_ready(repo, gid=gid)
    repo.update_staging_snapshot_status(sid, "approved", approved_by="alice")

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        c = TestClient(app)
        r = c.post(f"/orchestrator/staging/{sid}/unapprove", json={"unapproved_by": "bob"})
        assert r.status_code == 200
        b = r.json()
        assert b["status"] == "review_ready"
        assert b["review_readiness"]["ready"] is True
        assert not b.get("approved_at")
        evs = repo.list_graph_run_events(gid, limit=50)
        una = [e for e in evs if e.event_type == RunEventType.STAGING_SNAPSHOT_UNAPPROVED]
        assert len(una) == 1
    finally:
        app.dependency_overrides.clear()


def test_unapprove_blocked_when_canon_exists(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    gid = uuid4()
    sid, rec = _seed_review_ready(repo, gid=gid)
    repo.update_staging_snapshot_status(sid, "approved")
    pub = PublicationSnapshotRecord(
        publication_snapshot_id=uuid4(),
        source_staging_snapshot_id=sid,
        payload_json=deepcopy(rec.snapshot_payload_json),
        visibility="private",
        published_at="2026-03-29T13:00:00+00:00",
    )
    repo.save_publication_snapshot(pub)

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        c = TestClient(app)
        r = c.post(f"/orchestrator/staging/{sid}/unapprove", json={})
        assert r.status_code == 409
        assert r.json()["detail"]["error_kind"] == "unapprove_blocked_canon_exists"
    finally:
        app.dependency_overrides.clear()


def test_approve_rejects_after_rejected(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    sid, _ = _seed_review_ready(repo)
    repo.update_staging_snapshot_status(
        sid, "rejected", rejected_by="x", rejection_reason=None
    )

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        c = TestClient(app)
        r = c.post(f"/orchestrator/staging/{sid}/approve", json={})
        assert r.status_code == 409
        assert r.json()["detail"]["reason"] == "staging_rejected"
    finally:
        app.dependency_overrides.clear()
