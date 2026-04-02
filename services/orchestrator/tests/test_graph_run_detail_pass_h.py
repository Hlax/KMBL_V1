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
            input_payload_json={
                "identity_context": {"identity_id": str(iden), "profile_summary": "x"},
            },
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
        assert body["summary"].get("graph_run_identity_id") is None
        trace = body.get("identity_trace")
        assert trace is not None
        assert trace["thread_identity_id"] == str(iden)
        pic = trace.get("planner_identity_context") or {}
        assert pic.get("identity_id") == str(iden)
        assert body["summary"]["run_state_hint"] == "completed"
        assert body["summary"]["attention_state"] == "completed_no_staging"
        assert "quality_metrics" in body["summary"]
        assert "pressure_summary" in body["summary"]
        qm = body["summary"]["quality_metrics"]
        assert qm["event_count"] == 0
        assert qm["generator_invocation_flag_count"] == 0
        assert len(body["role_invocations"]) == 1
        assert body["role_invocations"][0]["role_type"] == "planner"
        assert len(body["timeline"]) == 2
        kinds = [t["kind"] for t in body["timeline"]]
        assert "run_started" in kinds and "run_completed" in kinds
    finally:
        app.dependency_overrides.clear()


def test_graph_run_detail_includes_graph_run_identity_id_when_set(clear_singleton: None) -> None:
    tid = uuid4()
    gid = uuid4()
    iden = uuid4()
    gr_iden = uuid4()
    repo = InMemoryRepository()
    repo.ensure_thread(
        ThreadRecord(thread_id=tid, identity_id=iden, thread_kind="build", status="active")
    )
    repo.save_graph_run(
        GraphRunRecord(
            graph_run_id=gid,
            thread_id=tid,
            identity_id=gr_iden,
            trigger_type="prompt",
            status="completed",
            started_at="2026-03-29T10:00:00+00:00",
            ended_at="2026-03-29T10:05:00+00:00",
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
        assert body["summary"]["graph_run_identity_id"] == str(gr_iden)
        # Effective identity in summary prefers graph_run.identity_id over thread.
        assert body["summary"]["identity_id"] == str(gr_iden)
        trace = body.get("identity_trace")
        assert trace is not None
        assert trace["thread_identity_id"] == str(iden)
        assert trace["graph_run_identity_id"] == str(gr_iden)
    finally:
        app.dependency_overrides.clear()


def test_graph_run_detail_generator_routing_hints_persisted(clear_singleton: None) -> None:
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
            role_type="generator",
            provider_config_key="kmbl-generator-openai-image",
            input_payload_json={},
            status="completed",
            iteration_index=0,
            started_at="2026-03-29T10:01:00+00:00",
            ended_at="2026-03-29T10:02:00+00:00",
            routing_metadata_json={
                "kmb_routing_version": 3,
                "generator_route_kind": "kiloclaw_image_agent",
                "openai_image_route_applied": True,
                "image_generation_intent_kind": "gallery_strip",
                "budget_denial_reason": None,
                "route_reason": "kiloclaw_image_agent_route_applied",
            },
        )
    )

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get(f"/orchestrator/runs/{gid}/detail")
        assert r.status_code == 200
        body = r.json()
        invs = body["role_invocations"]
        assert len(invs) == 1
        g0 = invs[0]
        assert g0["routing_fact_source"] == "persisted"
        assert g0["routing_hints"]["generator_route_kind"] == "kiloclaw_image_agent"
        assert g0["routing_hints"]["openai_image_route_applied"] is True
    finally:
        app.dependency_overrides.clear()


def test_graph_run_detail_snapshot_skipped_attention_ok(clear_singleton: None) -> None:
    """Completed run with no staging row but staging_snapshot_skipped event → neutral attention."""
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
        RunEventType.STAGING_SNAPSHOT_SKIPPED,
        {"staging_snapshot_policy": "on_nomination", "marked_for_review": False},
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
        assert body["summary"]["attention_state"] == "completed_snapshot_skipped_by_policy"
        kinds = [t["kind"] for t in body["timeline"]]
        assert "staging_skipped" in kinds
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
