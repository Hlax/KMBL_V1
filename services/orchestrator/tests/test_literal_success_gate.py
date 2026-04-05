"""Tests for deterministic literal_success_checks gate."""

from __future__ import annotations

from uuid import uuid4

from kmbl_orchestrator.domain import EvaluationReportRecord
from kmbl_orchestrator.runtime.literal_success_gate import (
    apply_cool_lane_motion_signal_gate,
    apply_literal_success_checks,
    collect_static_artifact_search_blob,
    cool_lane_artifact_has_motion_signal,
)


def _minimal_report(status: str = "pass") -> EvaluationReportRecord:
    return EvaluationReportRecord(
        evaluation_report_id=uuid4(),
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        evaluator_invocation_id=uuid4(),
        build_candidate_id=uuid4(),
        status=status,
    )


def test_collect_static_artifact_search_blob_joins_content() -> None:
    bc = {
        "artifact_outputs": [
            {"role": "static_frontend_file_v1", "path": "x.html", "content": "<p>Hello GSAP</p>"},
        ]
    }
    blob = collect_static_artifact_search_blob(bc)
    assert "gsap" in blob


def test_apply_literal_success_checks_pass() -> None:
    r = _minimal_report("pass")
    bc = {
        "artifact_outputs": [
            {"role": "static_frontend_file_v1", "path": "i.html", "content": '<img src="https://cdn.example.com/face.jpg">'},
        ]
    }
    bs = {"literal_success_checks": ["https://cdn.example.com/face.jpg"]}
    out = apply_literal_success_checks(r, build_spec=bs, build_candidate=bc)
    assert out.status == "pass"
    assert out.metrics_json.get("literal_success_checks_passed") is True


def test_apply_literal_success_checks_downgrades_to_partial() -> None:
    r = _minimal_report("pass")
    bc = {
        "artifact_outputs": [
            {"role": "static_frontend_file_v1", "path": "i.html", "content": "<p>no url here</p>"},
        ]
    }
    bs = {"literal_success_checks": ["https://missing.example.com/a.jpg"]}
    out = apply_literal_success_checks(r, build_spec=bs, build_candidate=bc)
    assert out.status == "partial"
    assert "https://missing.example.com/a.jpg" in (out.metrics_json.get("literal_success_checks_failed") or [])


def test_dict_needle_form() -> None:
    r = _minimal_report("pass")
    bc = {"artifact_outputs": [{"role": "x", "path": "a", "content": "data-kmbl-motion"}]}
    bs = {"literal_success_checks": [{"needle": "data-kmbl-motion"}]}
    out = apply_literal_success_checks(r, build_spec=bs, build_candidate=bc)
    assert out.status == "pass"


def test_cool_lane_artifact_has_motion_signal_css() -> None:
    assert cool_lane_artifact_has_motion_signal(
        "<style>.x{transition:opacity 0.3s;}</style>",
    )
    assert cool_lane_artifact_has_motion_signal(
        "<style>@keyframes x{from{opacity:0}}</style>",
    )


def test_cool_lane_artifact_has_motion_signal_script() -> None:
    html = "<script>\nconst x = () => 1;\nconsole.log(x());\n</script>"
    assert cool_lane_artifact_has_motion_signal(html)


def test_apply_cool_lane_motion_signal_gate_pass() -> None:
    r = _minimal_report("pass")
    bc = {
        "artifact_outputs": [
            {
                "role": "static_frontend_file_v1",
                "content": "<style>a{transition:color 0.2s}</style><p>hi</p>",
            },
        ],
    }
    bs = {"execution_contract": {"lane": "cool_generation_v1"}}
    out = apply_cool_lane_motion_signal_gate(
        r,
        build_spec=bs,
        event_input={"cool_generation_lane": True},
        build_candidate=bc,
    )
    assert out.metrics_json.get("cool_lane_motion_signal_ok") is True


def test_apply_cool_lane_motion_signal_gate_skips_cannot_fulfill() -> None:
    r = _minimal_report("pass")
    bc = {
        "_kmbl_compliance": {"status": "cannot_fulfill"},
        "artifact_outputs": [{"role": "static_frontend_file_v1", "content": "<p>only</p>"}],
    }
    bs = {"execution_contract": {"lane": "cool_generation_v1"}}
    out = apply_cool_lane_motion_signal_gate(
        r,
        build_spec=bs,
        event_input={"cool_generation_lane": True},
        build_candidate=bc,
    )
    assert out.metrics_json.get("cool_lane_motion_signal_missing") is not True
