"""Duplicate static output rejection vs prior staging snapshots."""

from __future__ import annotations

from uuid import uuid4

from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    EvaluationReportRecord,
    StagingSnapshotRecord,
    ThreadRecord,
)
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.staging.build_snapshot import build_staging_snapshot_payload
from kmbl_orchestrator.staging.duplicate_rejection import (
    apply_duplicate_staging_rejection,
    fingerprint_build_candidate,
    fingerprint_from_snapshot_payload,
)


def _html() -> str:
    return "<!DOCTYPE html><html><head><title>x</title></head><body>ok</body></html>"


def test_fingerprint_matches_between_candidate_and_snapshot_payload() -> None:
    tid = uuid4()
    gid = uuid4()
    bcid = uuid4()
    bsid = uuid4()
    arts = [
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/index.html",
            "language": "html",
            "content": _html(),
            "bundle_id": "main",
            "entry_for_preview": True,
        }
    ]
    bc = BuildCandidateRecord(
        build_candidate_id=bcid,
        thread_id=tid,
        graph_run_id=gid,
        generator_invocation_id=uuid4(),
        build_spec_id=bsid,
        candidate_kind="content",
        working_state_patch_json={"static_frontend_preview_v1": {"entry_path": "component/preview/index.html"}},
        artifact_refs_json=arts,
    )
    ev = EvaluationReportRecord(
        evaluation_report_id=uuid4(),
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
    payload = build_staging_snapshot_payload(
        build_candidate=bc, evaluation_report=ev, thread=th, build_spec=None
    )
    fp1 = fingerprint_build_candidate(bc)
    fp2 = fingerprint_from_snapshot_payload(payload)
    assert fp1 == fp2
    assert fp1 is not None


def test_apply_duplicate_forces_fail_when_prior_snapshot_same_fingerprint() -> None:
    tid = uuid4()
    gid_old = uuid4()
    gid_new = uuid4()
    bcid_old = uuid4()
    bcid_new = uuid4()
    bsid = uuid4()
    html = _html()
    arts = [
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/index.html",
            "language": "html",
            "content": html,
            "bundle_id": "main",
            "entry_for_preview": True,
        }
    ]
    wsp = {"static_frontend_preview_v1": {"entry_path": "component/preview/index.html"}}
    bc_old = BuildCandidateRecord(
        build_candidate_id=bcid_old,
        thread_id=tid,
        graph_run_id=gid_old,
        generator_invocation_id=uuid4(),
        build_spec_id=bsid,
        candidate_kind="content",
        working_state_patch_json=wsp,
        artifact_refs_json=arts,
    )
    ev_old = EvaluationReportRecord(
        evaluation_report_id=uuid4(),
        thread_id=tid,
        graph_run_id=gid_old,
        evaluator_invocation_id=uuid4(),
        build_candidate_id=bcid_old,
        status="pass",
        summary="ok",
        issues_json=[],
        metrics_json={},
    )
    th = ThreadRecord(thread_id=tid, identity_id=None, thread_kind="build", status="active")
    payload = build_staging_snapshot_payload(
        build_candidate=bc_old, evaluation_report=ev_old, thread=th, build_spec=None
    )
    ssid = uuid4()
    repo = InMemoryRepository()
    repo.save_staging_snapshot(
        StagingSnapshotRecord(
            staging_snapshot_id=ssid,
            thread_id=tid,
            build_candidate_id=bcid_old,
            graph_run_id=gid_old,
            snapshot_payload_json=payload,
            status="review_ready",
        )
    )

    bc_new = BuildCandidateRecord(
        build_candidate_id=bcid_new,
        thread_id=tid,
        graph_run_id=gid_new,
        generator_invocation_id=uuid4(),
        build_spec_id=bsid,
        candidate_kind="content",
        working_state_patch_json=wsp,
        artifact_refs_json=list(arts),
    )
    report = EvaluationReportRecord(
        evaluation_report_id=uuid4(),
        thread_id=tid,
        graph_run_id=gid_new,
        evaluator_invocation_id=uuid4(),
        build_candidate_id=bcid_new,
        status="pass",
        summary="looks good",
        issues_json=[],
        metrics_json={},
    )
    out = apply_duplicate_staging_rejection(
        report,
        bc=bc_new,
        repo=repo,
        thread_id=tid,
        graph_run_id=gid_new,
    )
    assert out.status == "fail"
    assert out.metrics_json.get("duplicate_rejection") is True
    assert out.metrics_json.get("duplicate_of_staging_snapshot_id") == str(ssid)


def test_apply_duplicate_skips_when_no_prior() -> None:
    tid = uuid4()
    gid = uuid4()
    bcid = uuid4()
    bsid = uuid4()
    arts = [
        {
            "role": "static_frontend_file_v1",
            "path": "component/a.html",
            "language": "html",
            "content": _html(),
        }
    ]
    bc = BuildCandidateRecord(
        build_candidate_id=bcid,
        thread_id=tid,
        graph_run_id=gid,
        generator_invocation_id=uuid4(),
        build_spec_id=bsid,
        candidate_kind="content",
        working_state_patch_json={},
        artifact_refs_json=arts,
    )
    report = EvaluationReportRecord(
        evaluation_report_id=uuid4(),
        thread_id=tid,
        graph_run_id=gid,
        evaluator_invocation_id=uuid4(),
        build_candidate_id=bcid,
        status="pass",
        summary="ok",
        issues_json=[],
        metrics_json={},
    )
    repo = InMemoryRepository()
    out = apply_duplicate_staging_rejection(
        report,
        bc=bc,
        repo=repo,
        thread_id=tid,
        graph_run_id=gid,
    )
    assert out.status == "pass"
