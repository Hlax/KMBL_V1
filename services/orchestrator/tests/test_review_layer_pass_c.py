"""Pass C: staging list, proposal read-model, product proxy — persisted truth only."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from kmbl_orchestrator.api.main import app, get_repo
from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.domain import StagingSnapshotRecord, ThreadRecord
from kmbl_orchestrator.persistence.factory import reset_repository_singleton_for_tests
from kmbl_orchestrator.persistence.repository import InMemoryRepository


@pytest.fixture
def clear_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()


def _v1_payload() -> dict:
    """Minimal v1-shaped payload for read_model extraction."""
    return {
        "version": 1,
        "ids": {
            "thread_id": str(uuid4()),
            "graph_run_id": str(uuid4()),
            "build_candidate_id": str(uuid4()),
            "evaluation_report_id": str(uuid4()),
            "identity_id": None,
            "build_spec_id": str(uuid4()),
        },
        "summary": {"type": "app", "title": "My Title"},
        "evaluation": {"status": "pass", "summary": "Looks good", "issues": [], "metrics": {}},
        "preview": {"preview_url": "https://p.example", "sandbox_ref": "s"},
        "artifacts": {"artifact_refs": []},
        "metadata": {"working_state_patch": {}},
    }


def test_list_staging_newest_first_respects_limit() -> None:
    repo = InMemoryRepository()
    tid = uuid4()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    for i in range(5):
        rid = uuid4()
        repo.save_staging_snapshot(
            StagingSnapshotRecord(
                staging_snapshot_id=rid,
                thread_id=tid,
                build_candidate_id=uuid4(),
                snapshot_payload_json=_v1_payload(),
                preview_url=f"https://x{i}.example",
                status="review_ready",
                created_at=f"2026-03-{20+i:02d}T12:00:00+00:00",
            )
        )
    rows = repo.list_staging_snapshots(limit=3)
    assert len(rows) == 3
    assert rows[0].created_at >= rows[1].created_at >= rows[2].created_at


def test_list_staging_endpoint_lightweight_shape(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    tid = uuid4()
    iden = uuid4()
    repo.ensure_thread(
        ThreadRecord(thread_id=tid, identity_id=iden, thread_kind="build", status="active")
    )
    p1 = _v1_payload()
    p1["ids"]["identity_id"] = str(iden)
    sid = uuid4()
    repo.save_staging_snapshot(
        StagingSnapshotRecord(
            staging_snapshot_id=sid,
            thread_id=tid,
            build_candidate_id=uuid4(),
            identity_id=iden,
            graph_run_id=uuid4(),
            snapshot_payload_json=p1,
            preview_url="https://pv.example",
            status="review_ready",
            created_at="2026-03-29T10:00:00+00:00",
        )
    )
    repo.save_staging_snapshot(
        StagingSnapshotRecord(
            staging_snapshot_id=uuid4(),
            thread_id=tid,
            build_candidate_id=uuid4(),
            snapshot_payload_json=_v1_payload(),
            status="archived",
            created_at="2026-03-29T11:00:00+00:00",
        )
    )

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get("/orchestrator/staging?limit=20")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 2
        assert "proposals" not in body
        assert "snapshot_payload_json" not in str(body)
        for s in body["snapshots"]:
            assert "snapshot_payload_json" not in s
            assert "evaluation_summary" in s
            assert "review_readiness" in s
            assert "title" in s
            assert s["payload_version"] == 1
    finally:
        app.dependency_overrides.clear()


def test_list_proposals_operator_queue_sorted(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    tid = uuid4()
    iden = uuid4()
    repo.ensure_thread(
        ThreadRecord(thread_id=tid, identity_id=iden, thread_kind="build", status="active")
    )
    p1 = _v1_payload()
    p1["ids"]["identity_id"] = str(iden)
    sid = uuid4()
    repo.save_staging_snapshot(
        StagingSnapshotRecord(
            staging_snapshot_id=sid,
            thread_id=tid,
            build_candidate_id=uuid4(),
            identity_id=iden,
            graph_run_id=uuid4(),
            snapshot_payload_json=p1,
            preview_url="https://pv.example",
            status="review_ready",
            created_at="2026-03-29T10:00:00+00:00",
        )
    )
    repo.save_staging_snapshot(
        StagingSnapshotRecord(
            staging_snapshot_id=uuid4(),
            thread_id=tid,
            build_candidate_id=uuid4(),
            snapshot_payload_json=_v1_payload(),
            status="archived",
            created_at="2026-03-29T11:00:00+00:00",
        )
    )

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get("/orchestrator/proposals?limit=20")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 2
        assert body.get("basis") == "persisted_rows_only"
        assert "snapshot_payload_json" not in str(body)
        props = body["proposals"]
        assert props[0]["staging_status"] == "review_ready"
        assert props[0]["review_action_state"] == "ready_for_review"
        assert props[0]["linked_publication_count"] == 0
        prop = props[0]
        assert prop["proposal_id"] == str(sid)
        assert prop["staging_snapshot_id"] == str(sid)
        assert prop["title"] == "My Title"
        assert prop["summary"] == "My Title"
        assert prop["evaluation_summary"] == "Looks good"
        assert prop["staging_status"] == "review_ready"
        assert prop["review_readiness"]["ready"] is True
        assert props[1]["review_action_state"] == "not_actionable"
    finally:
        app.dependency_overrides.clear()


def test_list_filter_identity_and_status(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    tid = uuid4()
    id_a = uuid4()
    id_b = uuid4()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    repo.save_staging_snapshot(
        StagingSnapshotRecord(
            staging_snapshot_id=uuid4(),
            thread_id=tid,
            build_candidate_id=uuid4(),
            identity_id=id_a,
            snapshot_payload_json=_v1_payload(),
            status="review_ready",
            created_at="2026-03-29T10:00:00+00:00",
        )
    )

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get(f"/orchestrator/staging?identity_id={id_b}")
        assert r.json()["count"] == 0
        r2 = client.get(f"/orchestrator/staging?identity_id={id_a}")
        assert r2.json()["count"] == 1
        r3 = client.get("/orchestrator/staging?status=review_ready")
        assert r3.json()["count"] == 1
    finally:
        app.dependency_overrides.clear()


def test_get_staging_detail_derived_fields(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    tid = uuid4()
    sid = uuid4()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    pl = _v1_payload()
    repo.save_staging_snapshot(
        StagingSnapshotRecord(
            staging_snapshot_id=sid,
            thread_id=tid,
            build_candidate_id=uuid4(),
            snapshot_payload_json=pl,
            preview_url="https://pv.example",
            status="review_ready",
        )
    )

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get(f"/orchestrator/staging/{sid}")
        b = r.json()
        assert b["evaluation_summary"] == "Looks good"
        assert b["short_title"] == "My Title"
        assert b["preview_url"] == "https://pv.example"
        assert b["payload_version"] == 1
        assert b["lineage"]["thread_id"] == str(tid)
        assert b["lineage"]["build_candidate_id"]
        assert b["evaluation"]["present"] is True
        assert b["evaluation"]["status"] == "pass"
        assert b["evaluation"]["issue_count"] == 0
        assert b["review_readiness_explanation"]
        assert "review_ready" in b["review_readiness_explanation"]
    finally:
        app.dependency_overrides.clear()


def test_get_staging_detail_404(clear_singleton: None) -> None:
    repo = InMemoryRepository()

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get(f"/orchestrator/staging/{uuid4()}")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_stub_run_timeline_includes_preview_on_staging_created() -> None:
    """Integration: timeline staging_snapshot_created carries preview_url (Pass C bridge)."""
    from kmbl_orchestrator.config import Settings
    from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
    from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker

    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(settings=Settings.model_construct(kiloclaw_transport="stub"))
    settings = Settings.model_construct(kiloclaw_transport="stub")
    tid, gid = persist_graph_run_start(
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
        initial={"thread_id": tid, "graph_run_id": gid, "event_input": {}},
    )
    evs = repo.list_graph_run_events(UUID(gid), limit=100)
    created = next(e for e in evs if e.event_type == "staging_snapshot_created")
    pj = created.payload_json or {}
    assert pj.get("preview_url")
    assert pj.get("staging_snapshot_id")
    assert pj.get("review_ready") is True
    assert pj.get("graph_run_id") == gid
    assert pj.get("thread_id") == tid
