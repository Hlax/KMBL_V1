"""Pass B: staging gating, generator/planner integrity, deterministic snapshot payload, GET staging API."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from kmbl_orchestrator.api.main import app, get_repo
from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.contracts.planner_normalize import (
    compact_planner_wire_output,
    normalize_build_spec_for_persistence,
)
from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    BuildSpecRecord,
    EvaluationReportRecord,
    StagingSnapshotRecord,
    ThreadRecord,
)
from kmbl_orchestrator.contracts.normalized_errors import staging_integrity_failure
from kmbl_orchestrator.domain import CheckpointRecord
from kmbl_orchestrator.errors import RoleInvocationFailed, StagingIntegrityFailed
from kmbl_orchestrator.runtime.run_failure_view import build_run_failure_view
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.persistence.factory import reset_repository_singleton_for_tests
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker
from kmbl_orchestrator.staging.build_snapshot import build_staging_snapshot_payload
from kmbl_orchestrator.staging.integrity import (
    validate_generator_output_for_candidate,
    validate_preview_integrity,
)


@pytest.fixture
def clear_singleton_and_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setenv("KILOCLAW_TRANSPORT", "stub")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()


def test_normalize_build_spec_defaults_missing_type_title() -> None:
    out, missing = normalize_build_spec_for_persistence({})
    assert out["type"] == "generic"
    assert out["title"] == "Untitled Build"
    assert set(missing) == {"type", "title"}


def test_compact_planner_wire_output_caps_lists() -> None:
    long_list = [f"criterion-{i}" for i in range(40)]
    raw = {
        "build_spec": {
            "type": "static_frontend_file_v1",
            "title": "T",
            "identity_source": {
                "url": "https://example.com/",
                "profile_summary": "x" * 400,
                "crawled_pages": [f"https://example.com/p{i}" for i in range(20)],
                "image_refs": [f"https://img{i}.example/x.png" for i in range(20)],
            },
        },
        "constraints": {},
        "success_criteria": long_list,
        "evaluation_targets": long_list,
    }
    out = compact_planner_wire_output(raw)
    assert len(out["success_criteria"]) == 14
    assert len(out["evaluation_targets"]) == 18
    iso = out["build_spec"]["identity_source"]
    assert len(iso["crawled_pages"]) == 6
    assert len(iso["image_refs"]) == 8
    assert len(iso["profile_summary"]) <= 240
    assert out["_kmbl_planner_metadata"]["compact_wire_output"] is True


def test_validate_generator_rejects_empty_payload() -> None:
    with pytest.raises(ValueError, match="non-empty primary field"):
        validate_generator_output_for_candidate({})


def test_build_staging_snapshot_payload_deterministic() -> None:
    tid = uuid4()
    gid = uuid4()
    bcid = uuid4()
    genv = uuid4()
    bsid = uuid4()
    evid = uuid4()
    bc = BuildCandidateRecord(
        build_candidate_id=bcid,
        thread_id=tid,
        graph_run_id=gid,
        generator_invocation_id=genv,
        build_spec_id=bsid,
        candidate_kind="content",
        working_state_patch_json={"a": 1},
        artifact_refs_json=[{"r": 1}],
        preview_url="https://x.example/p",
        sandbox_ref="sbx",
    )
    ev = EvaluationReportRecord(
        evaluation_report_id=evid,
        thread_id=tid,
        graph_run_id=gid,
        evaluator_invocation_id=uuid4(),
        build_candidate_id=bcid,
        status="pass",
        summary="ok",
        issues_json=[],
        metrics_json={},
    )
    th = ThreadRecord(thread_id=tid, identity_id=None, thread_kind="build", status="active")
    spec = BuildSpecRecord(
        build_spec_id=bsid,
        thread_id=tid,
        graph_run_id=gid,
        planner_invocation_id=uuid4(),
        spec_json={"type": "t", "title": "T"},
        constraints_json={},
        success_criteria_json=[],
        evaluation_targets_json=[],
    )
    a = build_staging_snapshot_payload(
        build_candidate=bc, evaluation_report=ev, thread=th, build_spec=spec
    )
    b = build_staging_snapshot_payload(
        build_candidate=bc, evaluation_report=ev, thread=th, build_spec=spec
    )
    assert a == b
    assert a["version"] == 1
    assert a["ids"]["thread_id"] == str(tid)


def test_evaluator_fail_stages_after_max_iterations() -> None:
    """Evaluator fail iterates through max_iterations, then stages with fail status.

    Generator-first principle: usable output always reaches staging so operators
    can review it, even when the evaluator reports failure.
    """
    class EvalAlwaysFail:
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
                    "build_spec": {"type": "x", "title": "y", "steps": []},
                    "constraints": {},
                    "success_criteria": [],
                    "evaluation_targets": [],
                }
            if role_type == "generator":
                return {
                    "proposed_changes": {"f": 1},
                    "artifact_outputs": [],
                    "updated_state": {},
                    "sandbox_ref": "s",
                    "preview_url": "https://p.example",
                }
            if role_type == "evaluator":
                return {
                    "status": "fail",
                    "summary": "no",
                    "issues": [{"code": "x"}],
                    "artifacts": [],
                    "metrics": {},
                }
            raise AssertionError(role_type)

    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(client=EvalAlwaysFail())
    settings = Settings.model_construct(
        kiloclaw_transport="stub",
        staging_snapshot_policy="always",
    )
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input={},
    )
    final = run_graph(
        repo=repo,
        invoker=invoker,
        settings=settings,
        initial={
            "thread_id": tid,
            "graph_run_id": gid,
            "event_input": {},
            "max_iterations": 1,
        },
    )
    assert final.get("staging_snapshot_id") is not None
    evs = repo.list_graph_run_events(UUID(gid), limit=80)
    types = [e.event_type for e in evs]
    assert "staging_snapshot_created" in types


def test_stub_pass_creates_persisted_staging_snapshot() -> None:
    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(
        settings=Settings.model_construct(
            kiloclaw_transport="stub",
            staging_snapshot_policy="always",
        )
    )
    settings = Settings.model_construct(
        kiloclaw_transport="stub",
        staging_snapshot_policy="always",
    )
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input={},
    )
    final = run_graph(
        repo=repo,
        invoker=invoker,
        settings=settings,
        initial={"thread_id": tid, "graph_run_id": gid, "event_input": {}},
    )
    ssid = final.get("staging_snapshot_id")
    assert ssid
    rec = repo.get_staging_snapshot(UUID(str(ssid)))
    assert rec is not None
    bc = repo.get_latest_build_candidate_for_graph_run(UUID(gid))
    assert bc is not None
    assert rec.snapshot_payload_json.get("version") == 1
    assert rec.snapshot_payload_json["ids"]["build_candidate_id"] == str(bc.build_candidate_id)
    evs = repo.list_graph_run_events(UUID(gid), limit=80)
    created = next(e for e in evs if e.event_type == "staging_snapshot_created")
    assert (created.payload_json or {}).get("review_ready") is True


def test_staging_integrity_failure_surfaces_on_run_status() -> None:
    repo = InMemoryRepository()
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input={},
    )
    gid_u = UUID(gid)
    tid_u = UUID(tid)
    repo.save_checkpoint(
        CheckpointRecord(
            checkpoint_id=uuid4(),
            thread_id=tid_u,
            graph_run_id=gid_u,
            checkpoint_kind="interrupt",
            state_json={
                "orchestrator_error": {
                    "error_kind": "staging_integrity",
                    "error_message": "bad preview",
                    "failure": staging_integrity_failure(
                        reason="preview_integrity",
                        message="bad preview",
                        details={"build_candidate_id": "x"},
                    ),
                    "staging_reason": "preview_integrity",
                }
            },
            context_compaction_json=None,
        )
    )
    repo.update_graph_run_status(gid_u, "failed", "2020-01-01T00:00:00+00:00")
    fv = build_run_failure_view(repo, gid_u, status="failed")
    assert fv["error_kind"] == "staging_integrity"
    assert fv["failure"] is not None
    assert fv["failure"].get("reason") == "preview_integrity"


def test_generator_empty_fails_invocation() -> None:
    class GenEmpty:
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
                    "build_spec": {"type": "x", "title": "y", "steps": []},
                    "constraints": {},
                    "success_criteria": [],
                    "evaluation_targets": [],
                }
            if role_type == "generator":
                return {
                    "proposed_changes": {},
                    "artifact_outputs": [],
                    "updated_state": {},
                }
            raise AssertionError(role_type)

    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(client=GenEmpty())
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


def test_planner_persists_with_normalized_defaults() -> None:
    class PlannerSparse:
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
                    "build_spec": {"steps": []},
                    "constraints": {},
                    "success_criteria": [],
                    "evaluation_targets": [],
                }
            if role_type == "generator":
                return {
                    "proposed_changes": {"a": 1},
                    "artifact_outputs": [],
                    "updated_state": {},
                    "preview_url": "https://ok.example",
                }
            if role_type == "evaluator":
                return {
                    "status": "pass",
                    "summary": "",
                    "issues": [],
                    "artifacts": [],
                    "metrics": {},
                }
            raise AssertionError(role_type)

    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(client=PlannerSparse())
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
    bs = repo.get_latest_build_spec_for_graph_run(UUID(gid))
    assert bs is not None
    assert bs.spec_json.get("type") == "generic"
    assert bs.spec_json.get("title") == "Untitled Build"
    raw = bs.raw_payload_json or {}
    meta = raw.get("_kmbl_planner_metadata") or {}
    assert "type" in meta.get("normalized_missing_fields", [])


def test_preview_invalid_blocks_staging_graph_fails() -> None:
    class BadPreview:
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
                    "build_spec": {"type": "x", "title": "y", "steps": []},
                    "constraints": {},
                    "success_criteria": [],
                    "evaluation_targets": [],
                }
            if role_type == "generator":
                return {
                    "proposed_changes": {"a": 1},
                    "artifact_outputs": [],
                    "updated_state": {},
                    "preview_url": "not-a-url",
                }
            if role_type == "evaluator":
                return {
                    "status": "pass",
                    "summary": "",
                    "issues": [],
                    "artifacts": [],
                    "metrics": {},
                }
            raise AssertionError(role_type)

    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(client=BadPreview())
    settings = Settings.model_construct(kiloclaw_transport="stub")
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input={},
    )
    with pytest.raises(StagingIntegrityFailed) as ei:
        run_graph(
            repo=repo,
            invoker=invoker,
            settings=settings,
            initial={"thread_id": tid, "graph_run_id": gid, "event_input": {}},
        )
    assert ei.value.reason == "preview_integrity"
    fv = build_run_failure_view(repo, UUID(gid), status="failed")
    assert fv["error_kind"] == "staging_integrity"
    assert (fv.get("failure") or {}).get("reason") == "preview_integrity"
    evs = repo.list_graph_run_events(UUID(gid), limit=80)
    assert any(
        e.event_type == "staging_snapshot_blocked"
        and (e.payload_json or {}).get("reason") == "preview_integrity"
        for e in evs
    )


def test_preview_required_without_url_blocks_staging() -> None:
    bc = BuildCandidateRecord(
        build_candidate_id=uuid4(),
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        generator_invocation_id=uuid4(),
        build_spec_id=uuid4(),
        candidate_kind="content",
        preview_url=None,
    )
    ev = EvaluationReportRecord(
        evaluation_report_id=uuid4(),
        thread_id=bc.thread_id,
        graph_run_id=bc.graph_run_id,
        evaluator_invocation_id=uuid4(),
        build_candidate_id=bc.build_candidate_id,
        status="pass",
        metrics_json={"preview_required": True},
    )
    with pytest.raises(ValueError, match="preview_required"):
        validate_preview_integrity(bc, ev)


def test_get_staging_api_persisted_only(clear_singleton_and_settings: None) -> None:
    repo = InMemoryRepository()
    ssid = uuid4()
    tid = uuid4()
    repo.ensure_thread(ThreadRecord(thread_id=tid, thread_kind="build", status="active"))
    repo.save_staging_snapshot(
        StagingSnapshotRecord(
            staging_snapshot_id=ssid,
            thread_id=tid,
            build_candidate_id=uuid4(),
            snapshot_payload_json={"k": 1},
            preview_url="https://x.example",
        )
    )

    def _override_repo() -> InMemoryRepository:
        return repo

    app.dependency_overrides[get_repo] = _override_repo
    try:
        client = TestClient(app)
        r = client.get(f"/orchestrator/staging/{ssid}")
        assert r.status_code == 200
        body = r.json()
        assert body["snapshot_payload_json"] == {"k": 1}
        assert body["review_readiness"]["ready"] is True
        assert body["review_readiness"]["staging_status"] == "review_ready"
        r404 = client.get(f"/orchestrator/staging/{uuid4()}")
        assert r404.status_code == 404
    finally:
        app.dependency_overrides.clear()
