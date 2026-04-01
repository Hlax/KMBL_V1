"""Materialize review snapshot from live working staging."""

from __future__ import annotations

from uuid import uuid4

import pytest

from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    BuildSpecRecord,
    EvaluationReportRecord,
    GraphRunRecord,
    ThreadRecord,
    WorkingStagingRecord,
)
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.staging.materialize_review_snapshot import (
    materialize_review_snapshot_from_live,
)


def _seed_thread_with_provenance(repo: InMemoryRepository) -> tuple:
    tid = uuid4()
    gid = uuid4()
    bcid = uuid4()
    bsid = uuid4()
    ginv = uuid4()
    evid = uuid4()
    einv = uuid4()

    repo.ensure_thread(
        ThreadRecord(thread_id=tid, thread_kind="build", status="active")
    )
    repo.save_graph_run(
        GraphRunRecord(
            graph_run_id=gid,
            thread_id=tid,
            identity_id=None,
            trigger_type="prompt",
            status="running",
        )
    )
    repo.save_build_spec(
        BuildSpecRecord(
            build_spec_id=bsid,
            thread_id=tid,
            graph_run_id=gid,
            planner_invocation_id=uuid4(),
            spec_json={"type": "t", "title": "T"},
            constraints_json={},
            success_criteria_json=[],
            evaluation_targets_json=[],
        )
    )
    repo.save_build_candidate(
        BuildCandidateRecord(
            build_candidate_id=bcid,
            thread_id=tid,
            graph_run_id=gid,
            generator_invocation_id=ginv,
            build_spec_id=bsid,
            candidate_kind="content",
            working_state_patch_json={},
            artifact_refs_json=[],
            preview_url=None,
            sandbox_ref=None,
        )
    )
    repo.save_evaluation_report(
        EvaluationReportRecord(
            evaluation_report_id=evid,
            thread_id=tid,
            graph_run_id=gid,
            evaluator_invocation_id=einv,
            build_candidate_id=bcid,
            status="pass",
            summary="ok",
            issues_json=[],
            metrics_json={},
        )
    )
    ws = WorkingStagingRecord(
        working_staging_id=uuid4(),
        thread_id=tid,
        identity_id=None,
        payload_json={"version": 1},
        revision=1,
        last_update_graph_run_id=gid,
        last_update_build_candidate_id=bcid,
    )
    repo.save_working_staging(ws)
    return tid, bcid, gid


def test_materialize_builds_snapshot_record() -> None:
    repo = InMemoryRepository()
    tid, bcid, gid = _seed_thread_with_provenance(repo)

    snap = materialize_review_snapshot_from_live(repo, tid)
    assert snap.thread_id == tid
    assert snap.build_candidate_id == bcid
    assert snap.graph_run_id == gid
    assert snap.status == "review_ready"
    assert snap.snapshot_payload_json.get("version") == 1
    meta = snap.snapshot_payload_json.get("metadata") or {}
    assert meta.get("preview_kind") in ("static", "external_url")


def test_materialize_requires_provenance() -> None:
    repo = InMemoryRepository()
    tid = uuid4()
    repo.ensure_thread(
        ThreadRecord(thread_id=tid, thread_kind="build", status="active")
    )
    ws = WorkingStagingRecord(
        working_staging_id=uuid4(),
        thread_id=tid,
        identity_id=None,
        payload_json={},
        revision=1,
        last_update_graph_run_id=None,
        last_update_build_candidate_id=None,
    )
    repo.save_working_staging(ws)

    with pytest.raises(ValueError, match="missing_provenance"):
        materialize_review_snapshot_from_live(repo, tid)
