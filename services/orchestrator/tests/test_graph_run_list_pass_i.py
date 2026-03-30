"""Pass I: GET /orchestrator/runs — persisted runs index."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from kmbl_orchestrator.api.main import app, get_repo
from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.domain import (
    GraphRunRecord,
    RoleInvocationRecord,
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


def test_list_graph_runs_newest_first_and_filters(clear_singleton: None) -> None:
    tid = uuid4()
    iden = uuid4()
    repo = InMemoryRepository()
    repo.ensure_thread(
        ThreadRecord(thread_id=tid, identity_id=iden, thread_kind="build", status="active")
    )
    g_old = uuid4()
    g_new = uuid4()
    repo.save_graph_run(
        GraphRunRecord(
            graph_run_id=g_old,
            thread_id=tid,
            trigger_type="prompt",
            status="completed",
            started_at="2026-03-28T10:00:00+00:00",
            ended_at="2026-03-28T10:05:00+00:00",
        )
    )
    repo.save_graph_run(
        GraphRunRecord(
            graph_run_id=g_new,
            thread_id=tid,
            trigger_type="prompt",
            status="running",
            started_at="2026-03-29T12:00:00+00:00",
        )
    )
    rid = uuid4()
    repo.save_role_invocation(
        RoleInvocationRecord(
            role_invocation_id=rid,
            graph_run_id=g_new,
            thread_id=tid,
            role_type="planner",
            provider_config_key="k",
            input_payload_json={},
            status="completed",
            iteration_index=2,
            started_at="2026-03-29T12:01:00+00:00",
        )
    )
    sid = uuid4()
    repo.save_staging_snapshot(
        StagingSnapshotRecord(
            staging_snapshot_id=sid,
            thread_id=tid,
            build_candidate_id=uuid4(),
            graph_run_id=g_new,
            snapshot_payload_json={},
            status="review_ready",
            created_at="2026-03-29T12:10:00+00:00",
        )
    )

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get("/orchestrator/runs?limit=10")
        assert r.status_code == 200
        body = r.json()
        assert body["basis"] == "persisted_rows_only"
        assert body["count"] == 2
        ids = [x["graph_run_id"] for x in body["runs"]]
        assert ids[0] == str(g_new) and ids[1] == str(g_old)

        top = body["runs"][0]
        assert top["thread_id"] == str(tid)
        assert top["identity_id"] == str(iden)
        assert top["role_invocation_count"] == 1
        assert top["max_iteration_index"] == 2
        assert top["latest_staging_snapshot_id"] == str(sid)
        assert top["attention_state"] == "healthy"

        f = client.get("/orchestrator/runs?status=completed")
        assert f.status_code == 200
        assert len(f.json()["runs"]) == 1
        assert f.json()["runs"][0]["graph_run_id"] == str(g_old)

        by_iden = client.get(f"/orchestrator/runs?identity_id={iden}")
        assert by_iden.status_code == 200
        assert len(by_iden.json()["runs"]) == 2
    finally:
        app.dependency_overrides.clear()


def test_list_graph_runs_invalid_identity(clear_singleton: None) -> None:
    repo = InMemoryRepository()

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        assert client.get("/orchestrator/runs?identity_id=not-a-uuid").status_code == 400
    finally:
        app.dependency_overrides.clear()
