"""HTTP route GET …/candidate-preview — latest build_candidate static assembly."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from kmbl_orchestrator.api.main import app, get_repo
from kmbl_orchestrator.domain import BuildCandidateRecord, GraphRunRecord, ThreadRecord
from kmbl_orchestrator.persistence.factory import reset_repository_singleton_for_tests
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.staging.candidate_preview import preview_payload_from_build_candidate

from test_static_preview_assembly import _v1_payload_with_static


@pytest.fixture
def clear_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setenv("OPENCLAW_TRANSPORT", "stub")
    reset_repository_singleton_for_tests()


def test_preview_payload_from_build_candidate_matches_assembly_shape() -> None:
    full = _v1_payload_with_static()
    refs = list(full["artifacts"]["artifact_refs"])
    wsp = dict(full["metadata"]["working_state_patch"])
    bc = BuildCandidateRecord(
        build_candidate_id=uuid4(),
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        generator_invocation_id=uuid4(),
        build_spec_id=uuid4(),
        candidate_kind="habitat",
        working_state_patch_json=wsp,
        artifact_refs_json=refs,
        raw_payload_json={},
    )
    p = preview_payload_from_build_candidate(bc)
    assert p["artifacts"]["artifact_refs"] == refs
    assert p["metadata"]["working_state_patch"] == wsp


def test_candidate_preview_http(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    tid = uuid4()
    gid = uuid4()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    repo.save_graph_run(
        GraphRunRecord(
            graph_run_id=gid,
            thread_id=tid,
            identity_id=None,
            trigger_type="prompt",
            status="completed",
            ended_at="2026-01-01T00:00:00+00:00",
        )
    )
    full = _v1_payload_with_static()
    refs = list(full["artifacts"]["artifact_refs"])
    wsp = dict(full["metadata"]["working_state_patch"])
    bc = BuildCandidateRecord(
        build_candidate_id=uuid4(),
        thread_id=tid,
        graph_run_id=gid,
        generator_invocation_id=uuid4(),
        build_spec_id=uuid4(),
        candidate_kind="habitat",
        working_state_patch_json=wsp,
        artifact_refs_json=refs,
        raw_payload_json={},
    )
    repo.save_build_candidate(bc)

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get(f"/orchestrator/runs/{gid}/candidate-preview")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
        assert b"Hi" in r.content or b"kmbl-static-preview" in r.content
    finally:
        app.dependency_overrides.clear()


def test_candidate_preview_404_without_build_candidate(clear_singleton: None) -> None:
    repo = InMemoryRepository()
    tid = uuid4()
    gid = uuid4()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    repo.save_graph_run(
        GraphRunRecord(
            graph_run_id=gid,
            thread_id=tid,
            identity_id=None,
            trigger_type="prompt",
            status="completed",
            ended_at="2026-01-01T00:00:00+00:00",
        )
    )

    def _ov() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _ov
    try:
        client = TestClient(app)
        r = client.get(f"/orchestrator/runs/{gid}/candidate-preview")
        assert r.status_code == 404
        detail = r.json().get("detail")
        if isinstance(detail, dict):
            assert detail.get("error_kind") == "candidate_preview_unavailable"
        else:
            assert "candidate_preview" in str(detail).lower()
    finally:
        app.dependency_overrides.clear()
