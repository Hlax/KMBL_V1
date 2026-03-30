"""Pass H: graph run detail read model endpoint — persisted rows only."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from kmbl_orchestrator.api.main import app, get_repo
from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.domain import (
    GraphRunRecord,
    RoleInvocationRecord,
    ThreadRecord,
)
from kmbl_orchestrator.persistence.factory import reset_repository_singleton_for_tests
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event


@pytest.fixture
def clear_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()


def test_graph_run_detail_endpoint_shape(clear_singleton: None) -> None:
    tid = uuid4()
    gid = uuid4()
    iden = uuid4()
    repo = InMemoryRepository()
    repo.ensure_thread(
        ThreadRecord(thread_id=tid, identity_id=iden, thread_kind="build", status="active")
    )
    repo.save_graph_run(
        GraphRunRecord(
            graph_run_id=gid,
            thread_id=tid,
            trigger_type="prompt",
            status="completed",
            started_at="2026-03-29T10:00:00+00:00",
            ended_at="2026-03-29T10:05:00+00:00",
        )
    )
    rid = uuid4()
    repo.save_role_invocation(
        RoleInvocationRecord(
            role_invocation_id=rid,
            graph_run_id=gid,
            thread_id=tid,
            role_type="planner",
            provider_config_key="local",
            input_payload_json={},
            status="completed",
            iteration_index=0,
            started_at="2026-03-29T10:01:00+00:00",
            ended_at="2026-03-29T10:02:00+00:00",
        )
    )
    append_graph_run_event(repo, gid, RunEventType.GRAPH_RUN_STARTED, {})
    append_graph_run_event(repo, gid, RunEventType.GRAPH_RUN_COMPLETED, {})

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get(f"/orchestrator/runs/{gid}/detail")
        assert r.status_code == 200
        body = r.json()
        assert body["basis"] == "persisted_rows_only"
        assert body["summary"]["graph_run_id"] == str(gid)
        assert body["summary"]["thread_id"] == str(tid)
        assert body["summary"]["identity_id"] == str(iden)
        assert body["summary"]["run_state_hint"] == "completed"
        assert body["summary"]["attention_state"] == "completed_no_staging"
        assert len(body["role_invocations"]) == 1
        assert body["role_invocations"][0]["role_type"] == "planner"
        assert len(body["timeline"]) == 2
        kinds = [t["kind"] for t in body["timeline"]]
        assert "run_started" in kinds and "run_completed" in kinds
    finally:
        app.dependency_overrides.clear()


def test_graph_run_detail_invalid_uuid(clear_singleton: None) -> None:
    repo = InMemoryRepository()

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        assert client.get("/orchestrator/runs/not-uuid/detail").status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_run_status_invalid_uuid(clear_singleton: None) -> None:
    repo = InMemoryRepository()

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        assert client.get("/orchestrator/runs/not-uuid").status_code == 400
    finally:
        app.dependency_overrides.clear()
