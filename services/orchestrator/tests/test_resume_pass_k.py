"""Pass K: POST /orchestrator/runs/{id}/resume — eligibility + mark running."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from kmbl_orchestrator.api.main import app, get_repo
from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.domain import CheckpointRecord, GraphRunRecord, ThreadRecord
from kmbl_orchestrator.persistence.factory import reset_repository_singleton_for_tests
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.runtime.run_resume import STALE_RUN_ERROR_KIND


@pytest.fixture
def clear_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()


def test_resume_paused_starts_background(
    clear_singleton: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "kmbl_orchestrator.api.main._run_graph_background",
        lambda **_: None,
    )
    tid = uuid4()
    gid = uuid4()
    repo = InMemoryRepository()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    repo.save_graph_run(
        GraphRunRecord(
            graph_run_id=gid,
            thread_id=tid,
            trigger_type="prompt",
            status="paused",
            started_at="2026-03-29T10:00:00+00:00",
            ended_at="2026-03-29T10:05:00+00:00",
        )
    )

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.post(f"/orchestrator/runs/{gid}/resume")
        assert r.status_code == 200
        assert r.json()["status"] == "running"
        gr = repo.get_graph_run(gid)
        assert gr is not None
        assert gr.status == "running"
        assert gr.ended_at is None
    finally:
        app.dependency_overrides.clear()


def test_resume_completed_409(clear_singleton: None) -> None:
    tid = uuid4()
    gid = uuid4()
    repo = InMemoryRepository()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
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

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.post(f"/orchestrator/runs/{gid}/resume")
        assert r.status_code == 409
        assert r.json()["detail"]["error_kind"] == "resume_not_eligible"
    finally:
        app.dependency_overrides.clear()


def test_resume_stale_failed_ok(
    clear_singleton: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "kmbl_orchestrator.api.main._run_graph_background",
        lambda **_: None,
    )
    tid = uuid4()
    gid = uuid4()
    repo = InMemoryRepository()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
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
    repo.save_checkpoint(
        CheckpointRecord(
            checkpoint_id=uuid4(),
            thread_id=tid,
            graph_run_id=gid,
            checkpoint_kind="interrupt",
            state_json={
                "orchestrator_error": {
                    "error_kind": STALE_RUN_ERROR_KIND,
                    "error_message": "stale",
                }
            },
            context_compaction_json=None,
        )
    )

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.post(f"/orchestrator/runs/{gid}/resume")
        assert r.status_code == 200
        assert repo.get_graph_run(gid).status == "running"
    finally:
        app.dependency_overrides.clear()


def test_detail_includes_resume_fields(clear_singleton: None) -> None:
    tid = uuid4()
    gid = uuid4()
    repo = InMemoryRepository()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    repo.save_graph_run(
        GraphRunRecord(
            graph_run_id=gid,
            thread_id=tid,
            trigger_type="prompt",
            status="paused",
            started_at="2026-03-29T10:00:00+00:00",
        )
    )

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get(f"/orchestrator/runs/{gid}/detail")
        assert r.status_code == 200
        b = r.json()
        assert b["resume_eligible"] is True
        assert b["retry_eligible"] is False
        assert b["resume_operator_explanation"]
    finally:
        app.dependency_overrides.clear()
