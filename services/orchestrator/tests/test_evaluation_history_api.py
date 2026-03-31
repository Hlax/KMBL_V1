"""Per-iteration evaluation history on GET /orchestrator/runs/{id} and repository list."""

from __future__ import annotations

import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from kmbl_orchestrator.api.main import app
from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.domain import EvaluationReportRecord
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.persistence.factory import reset_repository_singleton_for_tests
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker


@pytest.fixture
def clear_singleton_and_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setenv("KILOCLAW_TRANSPORT", "stub")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()


@pytest.fixture
def client(clear_singleton_and_settings: None) -> TestClient:
    return TestClient(app)


def test_list_evaluation_reports_orders_oldest_first(
    clear_singleton_and_settings: None,
) -> None:
    repo = InMemoryRepository()
    gid = uuid4()
    tid = uuid4()
    for i in range(3):
        repo.save_evaluation_report(
            EvaluationReportRecord(
                evaluation_report_id=uuid4(),
                thread_id=tid,
                graph_run_id=gid,
                evaluator_invocation_id=uuid4(),
                build_candidate_id=uuid4(),
                status="partial",
                summary=f"s{i}",
                created_at=f"2020-01-0{i + 1}T00:00:00+00:00",
            )
        )
    rows = repo.list_evaluation_reports_for_graph_run(gid)
    assert [r.summary for r in rows] == ["s0", "s1", "s2"]


def test_run_status_includes_evaluation_history_after_stub_graph(
    client: TestClient,
) -> None:
    """Stub transport: partial then pass → multiple evaluation rows on same graph run."""
    r = client.post("/orchestrator/runs/start", json={})
    assert r.status_code == 200
    gid = r.json()["graph_run_id"]
    deadline = time.time() + 60.0
    last: dict = {}
    while time.time() < deadline:
        s = client.get(f"/orchestrator/runs/{gid}")
        assert s.status_code == 200
        last = s.json()
        if last.get("status") in ("completed", "failed"):
            break
        time.sleep(0.05)
    else:
        pytest.fail("run did not reach terminal state")
    assert last.get("status") == "completed"
    hist = last.get("evaluation_history") or []
    assert len(hist) >= 2, "stub loop should record at least two evaluator passes"
    assert last.get("evaluation")["evaluation_report_id"] == hist[-1]["evaluation_report_id"]


def test_full_graph_direct_repo_lists_multiple_evaluations(
    clear_singleton_and_settings: None,
) -> None:
    settings = Settings.model_construct(
        kiloclaw_transport="stub",
        graph_max_iterations_default=3,
        habitat_image_generation_enabled=False,
    )
    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(settings=settings)
    tid_s, gid_s = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input={},
    )
    run_graph(
        repo=repo,
        invoker=invoker,
        settings=settings,
        initial={
            "thread_id": tid_s,
            "graph_run_id": gid_s,
            "event_input": {},
        },
    )
    from uuid import UUID

    hist = repo.list_evaluation_reports_for_graph_run(UUID(gid_s))
    assert len(hist) >= 2
