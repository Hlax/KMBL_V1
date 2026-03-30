"""Pass L: operator action visibility derived from graph_run_event rows only."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from kmbl_orchestrator.api.main import app, get_repo
from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.domain import GraphRunRecord, ThreadRecord
from kmbl_orchestrator.persistence.factory import reset_repository_singleton_for_tests
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event


@pytest.fixture
def clear_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()


def test_graph_run_detail_operator_actions_and_timeline_flags(clear_singleton: None) -> None:
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
    append_graph_run_event(repo, gid, RunEventType.GRAPH_RUN_STARTED, {})
    append_graph_run_event(
        repo,
        gid,
        RunEventType.GRAPH_RUN_RESUMED,
        {"basis": "persisted_rows_only"},
    )
    append_graph_run_event(repo, gid, RunEventType.GRAPH_RUN_COMPLETED, {})

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get(f"/orchestrator/runs/{gid}/detail")
        assert r.status_code == 200
        body = r.json()
        assert body["summary"]["resume_count"] == 1
        assert body["summary"]["last_resumed_at"] is not None

        ops = body["operator_actions"]
        assert len(ops) == 1
        assert ops[0]["kind"] == "graph_run_resumed"
        assert ops[0]["label"] == "Resume (operator)"
        assert ops[0]["details"] == {"basis": "persisted_rows_only"}

        tl = body["timeline"]
        by_kind = {t["kind"]: t for t in tl}
        assert by_kind["run_started"]["operator_triggered"] is False
        assert by_kind["operator_resume"]["operator_triggered"] is True
        assert by_kind["run_completed"]["operator_triggered"] is False
    finally:
        app.dependency_overrides.clear()
