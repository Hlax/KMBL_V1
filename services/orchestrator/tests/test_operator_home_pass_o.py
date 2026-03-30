"""Pass O — operator home summary endpoint."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from kmbl_orchestrator.api.main import app, get_repo
from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.domain import (
    GraphRunRecord,
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


def test_operator_summary_endpoint_shape(clear_singleton: None) -> None:
    tid = uuid4()
    iden = uuid4()
    repo = InMemoryRepository()
    repo.ensure_thread(
        ThreadRecord(thread_id=tid, identity_id=iden, thread_kind="build", status="active")
    )
    gid = uuid4()
    repo.save_graph_run(
        GraphRunRecord(
            graph_run_id=gid,
            thread_id=tid,
            trigger_type="prompt",
            status="failed",
            started_at="2026-03-29T10:00:00+00:00",
            ended_at="2026-03-29T10:05:00+00:00",
        )
    )
    bc = uuid4()
    s1 = uuid4()
    repo.save_staging_snapshot(
        StagingSnapshotRecord(
            staging_snapshot_id=s1,
            thread_id=tid,
            build_candidate_id=bc,
            snapshot_payload_json={},
            status="review_ready",
            created_at="2026-03-29T10:00:00+00:00",
        )
    )
    pub = uuid4()
    repo.save_publication_snapshot(
        PublicationSnapshotRecord(
            publication_snapshot_id=pub,
            source_staging_snapshot_id=s1,
            thread_id=tid,
            graph_run_id=None,
            identity_id=iden,
            payload_json={},
            visibility="private",
            published_at="2026-03-29T15:00:00+00:00",
        )
    )

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get("/orchestrator/operator-summary")
        assert r.status_code == 200
        body = r.json()
        assert body["basis"] == "persisted_rows_only"
        assert body["runtime"]["failed_count"] >= 1
        assert body["runtime"]["runs_needing_attention"] >= 1
        assert body["review_queue"]["published"] >= 1
        assert body["canon"]["has_current_publication"] is True
        assert body["canon"]["latest_publication_snapshot_id"] == str(pub)
    finally:
        app.dependency_overrides.clear()
