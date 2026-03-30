"""Static preview entry resolution and HTML assembly (staging payload only)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from kmbl_orchestrator.api.main import app, get_repo
from kmbl_orchestrator.domain import StagingSnapshotRecord, ThreadRecord
from kmbl_orchestrator.persistence.factory import reset_repository_singleton_for_tests
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.staging.static_preview_assembly import (
    NO_PREVIEWABLE_HTML,
    NO_STATIC_ARTIFACTS,
    assemble_static_preview_html,
    resolve_static_preview_entry_path,
)


def _v1_payload_with_static(
    *,
    with_gallery_strip: bool = False,
    html: str = "<!DOCTYPE html><html><head></head><body><p>Hi</p></body></html>",
    css: str = "body { color: navy; }",
) -> dict:
    artifacts: list[dict] = [
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/index.html",
            "language": "html",
            "content": html,
            "bundle_id": "main",
            "entry_for_preview": True,
        },
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/theme.css",
            "language": "css",
            "content": css,
            "bundle_id": "main",
        },
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/app.js",
            "language": "js",
            "content": "console.log('kmbl-static-preview');",
            "bundle_id": "main",
        },
    ]
    if with_gallery_strip:
        artifacts.insert(
            0,
            {
                "role": "gallery_strip_image_v1",
                "key": "k1",
                "url": "https://example.com/x.png",
            },
        )
    wsp = {"static_frontend_preview_v1": {"entry_path": "component/preview/index.html"}}
    return {
        "version": 1,
        "ids": {
            "thread_id": str(uuid4()),
            "graph_run_id": str(uuid4()),
            "build_candidate_id": str(uuid4()),
            "evaluation_report_id": str(uuid4()),
        },
        "summary": {"type": "content", "title": "t"},
        "evaluation": {"status": "pass", "summary": "", "issues": [], "metrics": {}},
        "preview": {"preview_url": None, "sandbox_ref": None},
        "artifacts": {"artifact_refs": artifacts},
        "metadata": {"working_state_patch": wsp},
    }


def test_resolve_entry_uses_bundle_and_preview() -> None:
    p = _v1_payload_with_static()
    path, err = resolve_static_preview_entry_path(p)
    assert err == ""
    assert path == "component/preview/index.html"


def test_resolve_fails_without_static() -> None:
    p = {
        "artifacts": {"artifact_refs": [{"role": "gallery_strip_image_v1", "key": "a", "url": "https://x.com/i.png"}]},
        "metadata": {"working_state_patch": {}},
    }
    path, err = resolve_static_preview_entry_path(p)
    assert path is None
    assert err == NO_STATIC_ARTIFACTS


def test_resolve_fails_without_html() -> None:
    p = {
        "artifacts": {
            "artifact_refs": [
                {
                    "role": "static_frontend_file_v1",
                    "path": "component/a.css",
                    "language": "css",
                    "content": "x{}",
                }
            ]
        },
        "metadata": {"working_state_patch": {}},
    }
    path, err = resolve_static_preview_entry_path(p)
    assert path is None
    assert err == NO_PREVIEWABLE_HTML


def test_assemble_inlines_css_and_js() -> None:
    p = _v1_payload_with_static(css="body { margin: 1px; }")
    entry, err = resolve_static_preview_entry_path(p)
    assert err == ""
    html, aerr = assemble_static_preview_html(p, entry_path=entry or "")
    assert aerr == ""
    assert html is not None
    assert "kmbl-static-preview" in html
    assert "margin: 1px" in html
    assert "data-kmbl-injected" in html


def test_mixed_gallery_and_static_still_previews() -> None:
    p = _v1_payload_with_static(with_gallery_strip=True)
    path, err = resolve_static_preview_entry_path(p)
    assert err == ""
    assert path == "component/preview/index.html"
    html, aerr = assemble_static_preview_html(p, entry_path=path or "")
    assert aerr == ""
    assert "<p>Hi</p>" in (html or "")


@pytest.fixture
def clear_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    reset_repository_singleton_for_tests()


def test_static_preview_http_serves_html(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    tid = uuid4()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    sid = uuid4()
    payload = _v1_payload_with_static()
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
        assert "kmbl-static-preview" in r.text
        assert "Hi" in r.text
    finally:
        app.dependency_overrides.clear()


def test_static_preview_http_404_when_empty(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    tid = uuid4()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    sid = uuid4()
    repo.save_staging_snapshot(
        StagingSnapshotRecord(
            staging_snapshot_id=sid,
            thread_id=tid,
            build_candidate_id=uuid4(),
            graph_run_id=uuid4(),
            snapshot_payload_json={"version": 1, "artifacts": {"artifact_refs": []}, "metadata": {}},
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
        assert r.status_code == 404
        body = r.json()
        assert body["detail"]["error_kind"] == "static_preview_unavailable"
    finally:
        app.dependency_overrides.clear()
