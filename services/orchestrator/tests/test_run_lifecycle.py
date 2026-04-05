"""Run lifecycle: duplicate start, cooperative interrupt API, interrupt checks."""

from __future__ import annotations

import threading
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from kmbl_orchestrator.api.main import app, get_repo
from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.domain import GraphRunRecord, ThreadRecord
from kmbl_orchestrator.errors import RunInterrupted
from kmbl_orchestrator.persistence.exceptions import ActiveGraphRunPerThreadConflictError
from kmbl_orchestrator.persistence.factory import reset_repository_singleton_for_tests
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.runtime.interrupt_checks import raise_if_interrupt_requested


@pytest.fixture
def clear_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setenv("OPENCLAW_TRANSPORT", "stub")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()


@pytest.fixture
def client(clear_singleton: None) -> TestClient:
    return TestClient(app)


def test_start_same_thread_after_interrupt_requested_returns_200_not_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same thread after interrupt_requested: prior run is finalized; second start returns 200."""
    monkeypatch.setattr(
        "kmbl_orchestrator.api.main._run_graph_background",
        lambda **kwargs: None,
    )
    r1 = client.post("/orchestrator/runs/start", json={})
    assert r1.status_code == 200
    tid = r1.json()["thread_id"]
    gid = r1.json()["graph_run_id"]
    assert client.post(f"/orchestrator/runs/{gid}/interrupt").status_code == 200
    st = client.get(f"/orchestrator/runs/{gid}")
    assert st.json()["status"] == "interrupt_requested"
    r2 = client.post("/orchestrator/runs/start", json={"thread_id": tid})
    assert r2.status_code == 200
    assert r2.json()["thread_id"] == tid
    assert r2.json()["graph_run_id"] != gid
    old = client.get(f"/orchestrator/runs/{gid}")
    assert old.status_code == 200
    assert old.json()["status"] == "interrupted"


def test_duplicate_start_same_thread_returns_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "kmbl_orchestrator.api.main._run_graph_background",
        lambda **kwargs: None,
    )
    r1 = client.post("/orchestrator/runs/start", json={})
    assert r1.status_code == 200
    tid = r1.json()["thread_id"]
    r2 = client.post("/orchestrator/runs/start", json={"thread_id": tid})
    assert r2.status_code == 409
    detail = r2.json()["detail"]
    assert detail["error_kind"] == "active_graph_run"
    assert "active_graph_run_id" in detail


def test_interrupt_endpoint_persists_request(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "kmbl_orchestrator.api.main._run_graph_background",
        lambda **kwargs: None,
    )
    r = client.post("/orchestrator/runs/start", json={})
    assert r.status_code == 200
    gid = r.json()["graph_run_id"]
    ir = client.post(f"/orchestrator/runs/{gid}/interrupt")
    assert ir.status_code == 200
    body = ir.json()
    assert body["status"] == "interrupt_requested"
    assert body.get("interrupt_requested_at")
    st = client.get(f"/orchestrator/runs/{gid}")
    assert st.status_code == 200
    assert st.json()["status"] == "interrupt_requested"


def test_interrupt_second_call_idempotent_no_duplicate_event_spam(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "kmbl_orchestrator.api.main._run_graph_background",
        lambda **kwargs: None,
    )
    r = client.post("/orchestrator/runs/start", json={})
    gid = r.json()["graph_run_id"]
    assert client.post(f"/orchestrator/runs/{gid}/interrupt").status_code == 200
    assert client.post(f"/orchestrator/runs/{gid}/interrupt").status_code == 200
    detail = client.get(f"/orchestrator/runs/{gid}/detail")
    assert detail.status_code == 200
    types = [e["event_type"] for e in detail.json().get("timeline", [])]
    assert types.count("interrupt_requested") == 1


def test_raise_if_interrupt_requested_raises() -> None:
    repo = InMemoryRepository()
    tid = uuid4()
    gid = uuid4()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    repo.save_graph_run(
        GraphRunRecord(
            graph_run_id=gid,
            thread_id=tid,
            trigger_type="prompt",
            status="interrupt_requested",
            interrupt_requested_at="2026-01-01T00:00:00+00:00",
        )
    )
    with pytest.raises(RunInterrupted):
        raise_if_interrupt_requested(repo, gid, tid)


def test_in_memory_rejects_second_active_graph_run_same_thread() -> None:
    tid = uuid4()
    repo = InMemoryRepository()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    g1 = uuid4()
    g2 = uuid4()
    repo.save_graph_run(
        GraphRunRecord(
            graph_run_id=g1,
            thread_id=tid,
            trigger_type="prompt",
            status="starting",
        )
    )
    with pytest.raises(ActiveGraphRunPerThreadConflictError):
        repo.save_graph_run(
            GraphRunRecord(
                graph_run_id=g2,
                thread_id=tid,
                trigger_type="prompt",
                status="starting",
            )
        )


def test_concurrent_post_start_same_thread_one_409(
    clear_singleton: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Races two POSTs after the read-check; persistence must reject the loser (or read-check wins)."""
    monkeypatch.setattr(
        "kmbl_orchestrator.api.main._run_graph_background",
        lambda **kwargs: None,
    )
    tid = uuid4()
    repo = InMemoryRepository()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        codes: list[int] = []
        barrier = threading.Barrier(2)

        def post_start() -> None:
            barrier.wait()
            codes.append(
                client.post(
                    "/orchestrator/runs/start",
                    json={"thread_id": str(tid), "trigger_type": "prompt", "event_input": {}},
                ).status_code
            )

        t1 = threading.Thread(target=post_start)
        t2 = threading.Thread(target=post_start)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert sorted(codes) == [200, 409]
    finally:
        app.dependency_overrides.clear()
