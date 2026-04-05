"""Habitat session: orchestrator-enforced strategy and API semantics."""

from __future__ import annotations

from uuid import uuid4

from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    EvaluationReportRecord,
    WorkingStagingRecord,
)
from kmbl_orchestrator.runtime.habitat_strategy import (
    build_spec_with_effective_habitat,
    effective_habitat_strategy_for_iteration,
    normalize_habitat_strategy_token,
)
from kmbl_orchestrator.staging.duplicate_rejection import (
    apply_fresh_habitat_duplicate_output_gate,
    fingerprint_build_candidate,
)
from kmbl_orchestrator.staging.habitat_surface_reset import (
    clear_working_staging_surface,
    fingerprint_working_staging_payload,
)


def test_kmbl_habitat_session_fresh_overrides_planner_continue_on_iter0() -> None:
    eff = effective_habitat_strategy_for_iteration(
        event_input={"kmbl_habitat_session": "fresh"},
        build_spec={"habitat_strategy": "continue"},
        iteration_index=0,
    )
    assert eff == "fresh_start"


def test_iteration_uses_planner_not_session_flag() -> None:
    eff = effective_habitat_strategy_for_iteration(
        event_input={"kmbl_habitat_session": "fresh"},
        build_spec={"habitat_strategy": "continue"},
        iteration_index=1,
    )
    assert eff == "continue"


def test_normalize_habitat_strategy_token() -> None:
    assert normalize_habitat_strategy_token("fresh_start") == "fresh_start"
    assert normalize_habitat_strategy_token(None) == "continue"


def test_build_spec_carries_effective_meta() -> None:
    bs = build_spec_with_effective_habitat({"title": "x", "type": "generic"}, "fresh_start")
    assert bs["habitat_strategy"] == "fresh_start"
    assert bs["_kmbl_orchestrator"]["habitat_strategy_effective"] == "fresh_start"


def test_fresh_habitat_duplicate_gate_flags_identical_bundle() -> None:
    tid = uuid4()
    gid = uuid4()
    bc = BuildCandidateRecord(
        build_candidate_id=uuid4(),
        thread_id=tid,
        graph_run_id=gid,
        generator_invocation_id=uuid4(),
        build_spec_id=uuid4(),
        candidate_kind="habitat",
        artifact_refs_json=[
            {
                "role": "static_frontend_file_v1",
                "path": "component/preview/index.html",
                "language": "html",
                "content": "<html><body><h1>Hi</h1></body></html>",
            }
        ],
    )
    fp = fingerprint_build_candidate(bc)
    assert fp is not None
    report = EvaluationReportRecord(
        evaluation_report_id=uuid4(),
        thread_id=tid,
        graph_run_id=gid,
        evaluator_invocation_id=uuid4(),
        build_candidate_id=bc.build_candidate_id,
        status="pass",
        summary="ok",
        issues_json=[],
        metrics_json={},
    )
    out = apply_fresh_habitat_duplicate_output_gate(
        report,
        bc=bc,
        prior_static_fingerprint=fp,
        iteration_index=0,
        habitat_strategy_effective="fresh_start",
    )
    assert out.status == "partial"
    assert out.metrics_json.get("fresh_habitat_duplicate_bundle") is True


def test_clear_working_staging_yields_fingerprint() -> None:
    ws = WorkingStagingRecord(
        working_staging_id=uuid4(),
        thread_id=uuid4(),
        payload_json={
            "artifacts": {
                "artifact_refs": [
                    {
                        "role": "static_frontend_file_v1",
                        "path": "a.html",
                        "language": "html",
                        "content": "<p>x</p>",
                    }
                ]
            }
        },
    )
    fp_before = fingerprint_working_staging_payload(ws.payload_json)
    ws2, _ = clear_working_staging_surface(ws, reason="test")
    assert fp_before is not None
    assert ws2.payload_json == {}
    assert ws2.revision == 0
