"""Pass N — proposals list query filters and sort modes."""

from __future__ import annotations

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


@pytest.fixture
def clear_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()


def _seed(repo: InMemoryRepository) -> tuple[UUID, UUID, UUID]:
    """Two staging rows (review_ready + approved) and one publication for the approved."""

    tid = uuid4()
    bc = uuid4()
    iden = uuid4()
    repo.ensure_thread(
        ThreadRecord(
            thread_id=tid,
            identity_id=iden,
            thread_kind="build",
            status="active",
        )
    )
    s1 = uuid4()
    s2 = uuid4()
    repo.save_staging_snapshot(
        StagingSnapshotRecord(
            staging_snapshot_id=s1,
            thread_id=tid,
            build_candidate_id=bc,
            snapshot_payload_json={"summary": {"title": "A"}},
            status="review_ready",
            created_at="2026-03-29T10:00:00+00:00",
        )
    )
    repo.save_staging_snapshot(
        StagingSnapshotRecord(
            staging_snapshot_id=s2,
            thread_id=tid,
            build_candidate_id=bc,
            snapshot_payload_json={"summary": {"title": "B"}},
            status="approved",
            created_at="2026-03-29T11:00:00+00:00",
        )
    )
    pub = uuid4()
    repo.save_publication_snapshot(
        PublicationSnapshotRecord(
            publication_snapshot_id=pub,
            source_staging_snapshot_id=s2,
            thread_id=tid,
            graph_run_id=None,
            identity_id=iden,
            payload_json={},
            visibility="private",
            published_at="2026-03-29T12:00:00+00:00",
        )
    )
    return s1, s2, pub


def test_proposals_filter_review_action_state(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    s1, s2, _pub = _seed(repo)

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get("/orchestrator/proposals?review_action_state=ready_for_review&limit=50")
        assert r.status_code == 200
        body = r.json()
        ids = {p["staging_snapshot_id"] for p in body["proposals"]}
        assert str(s1) in ids
        assert str(s2) not in ids

        r2 = client.get("/orchestrator/proposals?review_action_state=published&limit=50")
        assert r2.status_code == 200
        ids2 = {p["staging_snapshot_id"] for p in r2.json()["proposals"]}
        assert str(s2) in ids2
        assert str(s1) not in ids2
    finally:
        app.dependency_overrides.clear()


def test_proposals_invalid_review_action_state_400(clear_singleton: None) -> None:
    repo = InMemoryRepository()

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get("/orchestrator/proposals?review_action_state=not_a_real_state")
        assert r.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_proposals_has_publication_filter(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    _seed(repo)

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get("/orchestrator/proposals?has_publication=true&limit=50")
        assert r.status_code == 200
        assert len(r.json()["proposals"]) == 1
        r2 = client.get("/orchestrator/proposals?has_publication=false&limit=50")
        assert r2.status_code == 200
        assert len(r2.json()["proposals"]) == 1
    finally:
        app.dependency_overrides.clear()


def test_proposals_staging_status_filter(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    s1, _s2, _pub = _seed(repo)

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get("/orchestrator/proposals?staging_status=review_ready&limit=50")
        assert r.status_code == 200
        ids = {p["staging_snapshot_id"] for p in r.json()["proposals"]}
        assert ids == {str(s1)}
    finally:
        app.dependency_overrides.clear()
