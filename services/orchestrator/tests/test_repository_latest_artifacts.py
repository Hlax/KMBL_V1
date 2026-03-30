"""Latest artifact queries by graph_run_id (in-memory repo)."""

from __future__ import annotations

from uuid import uuid4

from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    BuildSpecRecord,
    EvaluationReportRecord,
)
from kmbl_orchestrator.persistence.repository import InMemoryRepository


def test_get_latest_per_graph_run() -> None:
    repo = InMemoryRepository()
    tid = uuid4()
    gid = uuid4()
    pi = uuid4()
    gi = uuid4()
    bi = uuid4()
    ei = uuid4()
    cid = uuid4()
    eid = uuid4()

    repo.save_build_spec(
        BuildSpecRecord(
            build_spec_id=uuid4(),
            thread_id=tid,
            graph_run_id=gid,
            planner_invocation_id=pi,
            spec_json={"title": "first"},
            status="active",
            created_at="2020-01-01T00:00:00+00:00",
        )
    )
    repo.save_build_spec(
        BuildSpecRecord(
            build_spec_id=uuid4(),
            thread_id=tid,
            graph_run_id=gid,
            planner_invocation_id=pi,
            spec_json={"title": "second"},
            status="active",
            created_at="2021-01-01T00:00:00+00:00",
        )
    )
    latest_bs = repo.get_latest_build_spec_for_graph_run(gid)
    assert latest_bs is not None
    assert latest_bs.spec_json.get("title") == "second"

    repo.save_build_candidate(
        BuildCandidateRecord(
            build_candidate_id=cid,
            thread_id=tid,
            graph_run_id=gid,
            generator_invocation_id=gi,
            build_spec_id=latest_bs.build_spec_id,
            candidate_kind="habitat",
            status="generated",
            created_at="2020-01-01T00:00:00+00:00",
        )
    )
    assert repo.get_latest_build_candidate_for_graph_run(gid) is not None

    repo.save_evaluation_report(
        EvaluationReportRecord(
            evaluation_report_id=eid,
            thread_id=tid,
            graph_run_id=gid,
            evaluator_invocation_id=ei,
            build_candidate_id=cid,
            status="pass",
            summary="ok",
            created_at="2020-01-01T00:00:00+00:00",
        )
    )
    ev = repo.get_latest_evaluation_report_for_graph_run(gid)
    assert ev is not None
    assert ev.summary == "ok"
