"""Live working-staging endpoint — mutable surface, not staging snapshots."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from kmbl_orchestrator.api.main import app, get_repo
from kmbl_orchestrator.domain import ThreadRecord, WorkingStagingRecord
from kmbl_orchestrator.persistence.factory import reset_repository_singleton_for_tests
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.staging.static_preview_assembly_live import live_habitat_preview_surface

from test_static_preview_assembly import _v1_payload_with_static


@pytest.fixture
def clear_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    reset_repository_singleton_for_tests()


def test_live_habitat_preview_surface_lists_paths() -> None:
    p = _v1_payload_with_static()
    surf = live_habitat_preview_surface(p)
    assert surf["preview_error"] in ("", None) or surf["preview_error"] is None
    assert "component/preview/index.html" in surf["html_paths"]
    assert len(surf["bundles"]) >= 1
    assert surf["bundles"][0].get("preview_entry_path")


def test_working_staging_live_http(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    tid = uuid4()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    payload = _v1_payload_with_static()
    ws = WorkingStagingRecord(
        working_staging_id=uuid4(),
        thread_id=tid,
        identity_id=None,
        payload_json=payload,
        revision=2,
        last_update_mode="patch",
    )
    repo.save_working_staging(ws)

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get(f"/orchestrator/working-staging/{tid}/live")
        assert r.status_code == 200
        body = r.json()
        assert body["kind"] == "live_working_staging"
        assert body["read_model"]["thread_id"] == str(tid)
        assert body["read_model"]["revision"] == 2
        assert body["preview_surface"]["default_entry_path"] == "component/preview/index.html"
        assert "component/preview/index.html" in body["preview_surface"]["html_paths"]
        assert body["thread"] is not None
        assert body["thread"]["thread_id"] == str(tid)
    finally:
        app.dependency_overrides.clear()


def test_staging_snapshot_static_preview_still_works(clear_singleton: None) -> None:
    """Regression: review snapshot static-preview route unchanged."""
    repo = InMemoryRepository()
    tid = uuid4()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    sid = uuid4()
    payload = _v1_payload_with_static()
    from kmbl_orchestrator.domain import StagingSnapshotRecord

    repo.save_staging_snapshot(
        StagingSnapshotRecord(
            staging_snapshot_id=sid,
            thread_id=tid,
            build_candidate_id=uuid4(),
            graph_run_id=uuid4(),
            snapshot_payload_json=payload,
            preview_url=None,
            status="review_ready",
            created_at="2026-03-29T12:00:00+00:00",
        )
    )

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get(f"/orchestrator/staging/{sid}/static-preview")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
        assert "Hi" in r.text
    finally:
        app.dependency_overrides.clear()
