"""Pass D: approve staging, publish, publication reads, timeline — persisted truth only."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from kmbl_orchestrator.api.main import app, get_repo
from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.domain import (
    PublicationSnapshotRecord,
    StagingSnapshotRecord,
    ThreadRecord,
)
from kmbl_orchestrator.persistence.factory import reset_repository_singleton_for_tests
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.runtime.run_events import RunEventType


@pytest.fixture
def clear_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()


def _v1_payload() -> dict:
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
        "summary": {"type": "app", "title": "T"},
        "evaluation": {"status": "pass", "summary": "ok", "issues": [], "metrics": {}},
        "preview": {"preview_url": "https://p.example", "sandbox_ref": None},
        "artifacts": {"artifact_refs": []},
        "metadata": {"working_state_patch": {}},
    }


def _seed_review_ready(
    repo: InMemoryRepository, *, gid: UUID | None = None
) -> tuple[UUID, StagingSnapshotRecord]:
    tid = uuid4()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    sid = uuid4()
    rec = StagingSnapshotRecord(
        staging_snapshot_id=sid,
        thread_id=tid,
        build_candidate_id=uuid4(),
        graph_run_id=gid,
        snapshot_payload_json=_v1_payload(),
        preview_url="https://pv.example",
        status="review_ready",
        created_at="2026-03-29T12:00:00+00:00",
    )
    repo.save_staging_snapshot(rec)
    return sid, rec


def test_approve_review_ready_then_idempotent(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    gid = uuid4()
    sid, _ = _seed_review_ready(repo, gid=gid)

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        c = TestClient(app)
        r = c.post(f"/orchestrator/staging/{sid}/approve", json={})
        assert r.status_code == 200
        b = r.json()
        assert b["status"] == "approved"
        assert b["review_readiness"]["approved"] is True
        assert b.get("approved_at")
        r2 = c.post(f"/orchestrator/staging/{sid}/approve", json={"approved_by": "op1"})
        assert r2.status_code == 200
        assert r2.json()["status"] == "approved"
        evs = repo.list_graph_run_events(gid, limit=50)
        appr = [e for e in evs if e.event_type == RunEventType.STAGING_SNAPSHOT_APPROVED]
        assert len(appr) == 1
        assert appr[0].payload_json.get("staging_snapshot_id") == str(sid)
    finally:
        app.dependency_overrides.clear()


def test_approve_rejects_non_review_ready(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    tid = uuid4()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    sid = uuid4()
    repo.save_staging_snapshot(
        StagingSnapshotRecord(
            staging_snapshot_id=sid,
            thread_id=tid,
            build_candidate_id=uuid4(),
            snapshot_payload_json=_v1_payload(),
            status="archived",
        )
    )

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        c = TestClient(app)
        r = c.post(f"/orchestrator/staging/{sid}/approve", json={})
        assert r.status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_publish_requires_approve(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    sid, _ = _seed_review_ready(repo)

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        c = TestClient(app)
        r = c.post(
            "/orchestrator/publication",
            json={"staging_snapshot_id": str(sid), "visibility": "private"},
        )
        assert r.status_code == 409
        assert r.json()["detail"]["reason"] == "staging_not_approved"
    finally:
        app.dependency_overrides.clear()


def test_publish_approved_copies_payload_and_timeline(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    gid = uuid4()
    sid, rec = _seed_review_ready(repo, gid=gid)
    repo.update_staging_snapshot_status(sid, "approved")

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        c = TestClient(app)
        r = c.post(
            "/orchestrator/publication",
            json={
                "staging_snapshot_id": str(sid),
                "visibility": "public",
                "published_by": "alice",
            },
        )
        assert r.status_code == 200
        out = r.json()
        assert out.get("published_by") == "alice"
        pid = out["publication_snapshot_id"]
        pub = repo.get_publication_snapshot(UUID(pid))
        assert pub is not None
        assert pub.payload_json == rec.snapshot_payload_json
        assert pub.visibility == "public"
        assert pub.published_by == "alice"

        repo.update_staging_snapshot_status(sid, "review_ready")
        mutated = repo.get_staging_snapshot(sid)
        assert mutated is not None
        pl = dict(mutated.snapshot_payload_json)
        pl["evaluation"] = {"status": "pass", "summary": "mutated", "issues": [], "metrics": {}}
        repo.save_staging_snapshot(mutated.model_copy(update={"snapshot_payload_json": pl}))

        pub2 = repo.get_publication_snapshot(UUID(pid))
        assert pub2 is not None
        assert pub2.payload_json == rec.snapshot_payload_json

        evs = repo.list_graph_run_events(gid, limit=50)
        pub_ev = [e for e in evs if e.event_type == RunEventType.PUBLICATION_SNAPSHOT_CREATED]
        assert len(pub_ev) == 1
        pj = pub_ev[0].payload_json
        assert pj.get("publication_snapshot_id") == pid
        assert pj.get("source_staging_snapshot_id") == str(sid)
        assert pj.get("visibility") == "public"
    finally:
        app.dependency_overrides.clear()


def test_second_publish_same_staging_rejected_409(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    sid, _ = _seed_review_ready(repo)
    repo.update_staging_snapshot_status(sid, "approved")

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        c = TestClient(app)
        r1 = c.post(
            "/orchestrator/publication",
            json={"staging_snapshot_id": str(sid), "visibility": "private"},
        )
        assert r1.status_code == 200
        r2 = c.post(
            "/orchestrator/publication",
            json={"staging_snapshot_id": str(sid), "visibility": "public"},
        )
        assert r2.status_code == 409
        d = r2.json()["detail"]
        assert d["error_kind"] == "publication_already_exists_for_staging"
        assert d["staging_snapshot_id"] == str(sid)
    finally:
        app.dependency_overrides.clear()


def test_publication_reads_order_and_404(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    tid = uuid4()
    iden = uuid4()
    repo.ensure_thread(
        ThreadRecord(thread_id=tid, identity_id=iden, thread_kind="build", status="active")
    )

    def mk_pub(n: str) -> None:
        sid = uuid4()
        repo.save_staging_snapshot(
            StagingSnapshotRecord(
                staging_snapshot_id=sid,
                thread_id=tid,
                build_candidate_id=uuid4(),
                identity_id=iden,
                snapshot_payload_json=_v1_payload(),
                status="approved",
                created_at=f"2026-03-{n}T12:00:00+00:00",
            )
        )
        pid = uuid4()
        repo.save_publication_snapshot(
            PublicationSnapshotRecord(
                publication_snapshot_id=pid,
                source_staging_snapshot_id=sid,
                identity_id=iden,
                thread_id=tid,
                payload_json=_v1_payload(),
                visibility="private",
                published_at=f"2026-03-{n}T15:00:00+00:00",
            )
        )

    mk_pub("10")
    mk_pub("20")

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        c = TestClient(app)
        lst = c.get("/orchestrator/publication?limit=10").json()
        assert lst["count"] == 2
        assert lst["publications"][0]["published_at"] >= lst["publications"][1]["published_at"]

        cur = c.get(f"/orchestrator/publication/current?identity_id={iden}")
        assert cur.status_code == 200
        assert cur.json()["published_at"] == lst["publications"][0]["published_at"]

        r404 = c.get(f"/orchestrator/publication/{uuid4()}")
        assert r404.status_code == 404

        rcur_empty = c.get("/orchestrator/publication/current")
        assert rcur_empty.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_publication_current_404_when_empty(clear_singleton: None) -> None:
    repo = InMemoryRepository()

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        c = TestClient(app)
        r = c.get("/orchestrator/publication/current")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_publication_detail_matches_persisted(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    sid = uuid4()
    tid = uuid4()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    pl = _v1_payload()
    repo.save_staging_snapshot(
        StagingSnapshotRecord(
            staging_snapshot_id=sid,
            thread_id=tid,
            build_candidate_id=uuid4(),
            snapshot_payload_json=pl,
            status="approved",
        )
    )
    pid = uuid4()
    repo.save_publication_snapshot(
        PublicationSnapshotRecord(
            publication_snapshot_id=pid,
            source_staging_snapshot_id=sid,
            thread_id=tid,
            payload_json=deepcopy(pl),
            visibility="private",
            published_at="2026-03-29T16:00:00+00:00",
        )
    )

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        c = TestClient(app)
        r = c.get(f"/orchestrator/publication/{pid}")
        assert r.status_code == 200
        body = r.json()
        assert body["payload_json"] == pl
        assert body["publication_lineage"]["source_staging_snapshot_id"] == str(sid)
    finally:
        app.dependency_overrides.clear()
