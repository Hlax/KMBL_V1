"""Amend chain: prior_staging_snapshot_id on row + payload ids."""

from __future__ import annotations

from uuid import uuid4

from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    BuildSpecRecord,
    EvaluationReportRecord,
    StagingSnapshotRecord,
    ThreadRecord,
)
from kmbl_orchestrator.staging.build_snapshot import build_staging_snapshot_payload
from kmbl_orchestrator.staging.read_model import staging_lineage_read_model


def test_build_staging_snapshot_payload_sets_prior_and_reuse_note() -> None:
    tid = uuid4()
    gid = uuid4()
    bcid = uuid4()
    genv = uuid4()
    bsid = uuid4()
    evid = uuid4()
    prior = uuid4()
    bc = BuildCandidateRecord(
        build_candidate_id=bcid,
        thread_id=tid,
        graph_run_id=gid,
        generator_invocation_id=genv,
        build_spec_id=bsid,
        candidate_kind="content",
        working_state_patch_json={},
        artifact_refs_json=[],
        preview_url=None,
        sandbox_ref=None,
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
    p = build_staging_snapshot_payload(
        build_candidate=bc,
        evaluation_report=ev,
        thread=th,
        build_spec=spec,
        prior_staging_snapshot_id=prior,
    )
    assert p["ids"]["prior_staging_snapshot_id"] == str(prior)
    meta = p.get("metadata") or {}
    assert isinstance(meta.get("content_reuse_note"), str)
    assert "generated images" in (meta.get("content_reuse_note") or "")
    assert meta.get("preview_kind") == "static"


def test_staging_lineage_includes_prior_from_row() -> None:
    tid = uuid4()
    prior = uuid4()
    sid = uuid4()
    rec = StagingSnapshotRecord(
        staging_snapshot_id=sid,
        thread_id=tid,
        build_candidate_id=uuid4(),
        graph_run_id=uuid4(),
        prior_staging_snapshot_id=prior,
        snapshot_payload_json={"version": 1},
    )
    lm = staging_lineage_read_model(rec, {})
    assert lm["prior_staging_snapshot_id"] == str(prior)
