"""Runtime hardening: async start, stale reconcile, contracts, GET failure view, idempotent polling."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kmbl_orchestrator.api.main import app
from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.domain import GraphRunRecord, ThreadRecord
from kmbl_orchestrator.errors import RoleInvocationFailed
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.persistence.factory import (
    get_repository,
    reset_repository_singleton_for_tests,
)
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.providers.kiloclaw import (
    KiloClawInvocationError,
    provider_failure,
)
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker
from kmbl_orchestrator.runtime.run_failure_view import build_run_failure_view
from kmbl_orchestrator.runtime.stale_run import reconcile_stale_running_graph_run


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


def test_start_returns_starting_quickly(client: TestClient) -> None:
    t0 = time.perf_counter()
    r = client.post("/orchestrator/runs/start", json={})
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "starting"
    assert body.get("graph_run_id")
    assert elapsed < 5.0, "start should return without waiting for graph completion"


def test_get_eventually_completed_after_start(client: TestClient) -> None:
    r = client.post("/orchestrator/runs/start", json={})
    gid = r.json()["graph_run_id"]
    deadline = time.time() + 60.0
    last = {}
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
    assert last.get("timeline_events")
    types = [e["event_type"] for e in last["timeline_events"]]
    assert "graph_run_started" in types
    assert "graph_run_completed" in types


def test_malformed_planner_persistence_contract_validation() -> None:
    class BadPlannerOut:
        def invoke_role(
            self,
            role_type: str,
            provider_config_key: str,
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            _ = provider_config_key
            _ = payload
            if role_type == "planner":
                return {
                    "build_spec": {
                        "type": "x",
                        "title": "y",
                        "steps": {},
                    },
                    "constraints": {},
                    "success_criteria": [],
                    "evaluation_targets": [],
                }
            raise AssertionError(role_type)

    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(client=BadPlannerOut())
    settings = Settings.model_construct(kiloclaw_transport="stub")
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input={},
    )
    with pytest.raises(RoleInvocationFailed) as ei:
        run_graph(
            repo=repo,
            invoker=invoker,
            settings=settings,
            initial={"thread_id": tid, "graph_run_id": gid, "event_input": {}},
        )
    assert ei.value.detail.get("error_kind") == "contract_validation"


def test_failed_role_invocation_surfaces_provider_error_on_get() -> None:
    class FailPlanner:
        def invoke_role(
            self,
            role_type: str,
            provider_config_key: str,
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            _ = provider_config_key
            _ = payload
            raise KiloClawInvocationError(
                "boom",
                normalized=provider_failure(
                    "provider said no",
                    error_kind="provider_error",
                    error_type="provider_error",
                ),
            )

    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(client=FailPlanner())
    settings = Settings.model_construct(kiloclaw_transport="stub")
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input={},
    )
    with pytest.raises(RoleInvocationFailed):
        run_graph(
            repo=repo,
            invoker=invoker,
            settings=settings,
            initial={"thread_id": tid, "graph_run_id": gid, "event_input": {}},
        )
    gr = repo.get_graph_run(UUID(gid))
    assert gr is not None
    assert gr.status == "failed"
    fv = build_run_failure_view(repo, UUID(gid), status="failed")
    assert fv["failure_phase"] == "planner"
    assert fv["error_kind"] == "provider_error"


def test_stale_running_reconciled_on_get(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setenv("ORCHESTRATOR_RUNNING_STALE_AFTER_SECONDS", "1")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()

    tid = uuid4()
    gid = uuid4()
    repo = get_repository(get_settings())
    repo.ensure_thread(
        ThreadRecord(thread_id=tid, thread_kind="build", status="active")
    )
    repo.save_graph_run(
        GraphRunRecord(
            graph_run_id=gid,
            thread_id=tid,
            trigger_type="prompt",
            status="running",
            started_at="2020-01-01T00:00:00+00:00",
        )
    )
    settings = get_settings()
    assert reconcile_stale_running_graph_run(repo, settings, gid) is True
    gr = repo.get_graph_run(gid)
    assert gr is not None
    assert gr.status == "failed"
    fv = build_run_failure_view(repo, gid, status="failed")
    assert fv["error_kind"] == "orchestrator_stale_run"


def test_graph_error_visible_from_background_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()

    repo = get_repository(get_settings())
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input={},
    )

    def boom_graph(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("simulated graph fault")

    with patch(
        "kmbl_orchestrator.application.run_lifecycle.run_graph",
        side_effect=boom_graph,
    ):
        client = TestClient(app)
        r = client.post("/orchestrator/runs/start", json={})
        assert r.status_code == 200
        gid2 = r.json()["graph_run_id"]
        deadline = time.time() + 5.0
        last = {}
        while time.time() < deadline:
            s = client.get(f"/orchestrator/runs/{gid2}")
            last = s.json()
            if last.get("status") == "failed":
                break
            time.sleep(0.05)
        else:
            pytest.fail("expected failed status after background error")
    assert last.get("error_kind") == "graph_error"
    assert "simulated graph fault" in (last.get("error_message") or "")


def test_repeated_get_after_stale_reconcile_is_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setenv("ORCHESTRATOR_RUNNING_STALE_AFTER_SECONDS", "1")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()

    tid = uuid4()
    gid = uuid4()
    repo = get_repository(get_settings())
    repo.ensure_thread(
        ThreadRecord(thread_id=tid, thread_kind="build", status="active")
    )
    repo.save_graph_run(
        GraphRunRecord(
            graph_run_id=gid,
            thread_id=tid,
            trigger_type="prompt",
            status="running",
            started_at="2020-01-01T00:00:00+00:00",
        )
    )
    client = TestClient(app)
    a = client.get(f"/orchestrator/runs/{gid}")
    b = client.get(f"/orchestrator/runs/{gid}")
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["status"] == "failed"
    assert b.json()["status"] == "failed"
    assert a.json()["error_kind"] == b.json()["error_kind"] == "orchestrator_stale_run"
    ev = repo.list_graph_run_events(gid, limit=50)
    failed_ev = [e for e in ev if e.event_type == "graph_run_failed"]
    assert len(failed_ev) == 1


def test_role_input_validation_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KILOCLAW_TRANSPORT", "stub")
    get_settings.cache_clear()
    invoker = DefaultRoleInvoker()
    gid = uuid4()
    tid = uuid4()
    inv, raw = invoker.invoke(
        graph_run_id=gid,
        thread_id=tid,
        role_type="planner",
        provider_config_key="k",
        input_payload={"not_thread_id": "x"},
        iteration_index=0,
    )
    assert inv.status == "failed"
    assert raw.get("error_kind") == "contract_validation"
    with pytest.raises(ValidationError):
        from kmbl_orchestrator.contracts.role_inputs import validate_role_input

        validate_role_input("planner", {"not_thread_id": "x"})
