"""Tests for cool_generation_v1 lane presets and compliance annotation."""

from __future__ import annotations

from uuid import uuid4

from kmbl_orchestrator.domain import EvaluationReportRecord
from kmbl_orchestrator.runtime.cool_generation_lane import (
    COOL_GENERATION_LANE_V1,
    annotate_cool_lane_generator_compliance,
    apply_cool_generation_lane_presets,
    apply_cool_lane_execution_acknowledgment_gates,
    apply_cool_lane_silent_acknowledgment_gate,
    cool_generation_lane_active,
    reference_pattern_to_literal_token,
    summarize_execution_contract_for_generator,
)


def test_cool_generation_lane_active_from_event() -> None:
    assert cool_generation_lane_active({"cool_generation_lane": True}, {})
    assert not cool_generation_lane_active({}, {})


def test_cool_generation_lane_active_from_execution_contract() -> None:
    assert cool_generation_lane_active(
        {},
        {"execution_contract": {"lane": COOL_GENERATION_LANE_V1}},
    )


def test_apply_presets_merges_literal_needles() -> None:
    bs, meta = apply_cool_generation_lane_presets(
        {
            "type": "x",
            "title": "t",
            "steps": [],
            "execution_contract": {"lane": COOL_GENERATION_LANE_V1},
        },
        {"cool_generation_lane": True},
        {"image_refs": ["https://cdn.example.com/p.jpg"]},
        {},
    )
    assert meta["applied"] is True
    needles = bs.get("literal_success_checks") or []
    joined = " ".join(str(x).lower() for x in needles)
    assert "https://cdn.example.com/p.jpg" in joined
    assert 'data-kmbl-cool-lane="1"' in joined or "data-kmbl-cool-lane" in joined
    assert "kmbl-cool-hero" in joined
    assert "kmbl-pattern-portrait-led-editorial-hero" in joined
    assert isinstance(bs.get("creative_brief"), dict)


def test_reference_pattern_to_literal_token() -> None:
    assert reference_pattern_to_literal_token("portrait_led_editorial_hero") == (
        "kmbl-pattern-portrait-led-editorial-hero"
    )


def test_summarize_execution_contract() -> None:
    s = summarize_execution_contract_for_generator(
        {
            "execution_contract": {
                "lane": COOL_GENERATION_LANE_V1,
                "pattern_rules": ["a"],
                "selected_reference_patterns": ["p1"],
            },
            "literal_success_checks": ["x", "y"],
        }
    )
    assert s.get("lane") == COOL_GENERATION_LANE_V1
    assert s.get("literal_success_checks_count") == 2
    assert s.get("literal_success_checks_preview") == ["x", "y"]


def test_annotate_compliance_silent_without_status() -> None:
    raw = annotate_cool_lane_generator_compliance(
        {"artifact_outputs": [{"role": "static_frontend_file_v1", "content": "<p>x</p>"}]},
        build_spec={"execution_contract": {"lane": COOL_GENERATION_LANE_V1}},
        event_input={"cool_generation_lane": True},
    )
    assert raw.get("_kmbl_compliance", {}).get("silent_acknowledgment") is True


def test_annotate_compliance_with_status() -> None:
    raw = annotate_cool_lane_generator_compliance(
        {
            "artifact_outputs": [{"role": "static_frontend_file_v1", "content": "<p>x</p>"}],
            "execution_acknowledgment": {"status": "executed"},
        },
        build_spec={"execution_contract": {"lane": COOL_GENERATION_LANE_V1}},
        event_input={"cool_generation_lane": True},
    )
    assert raw.get("_kmbl_compliance", {}).get("acknowledged") is True
    assert raw.get("_kmbl_compliance", {}).get("silent_acknowledgment") is not True


def test_annotate_compliance_invalid_status() -> None:
    raw = annotate_cool_lane_generator_compliance(
        {
            "artifact_outputs": [{"role": "static_frontend_file_v1", "content": "<p>x</p>"}],
            "execution_acknowledgment": {"status": "done"},
        },
        build_spec={"execution_contract": {"lane": COOL_GENERATION_LANE_V1}},
        event_input={"cool_generation_lane": True},
    )
    assert raw.get("_kmbl_compliance", {}).get("invalid_execution_acknowledgment_status") is True


def _report() -> EvaluationReportRecord:
    return EvaluationReportRecord(
        evaluation_report_id=uuid4(),
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        evaluator_invocation_id=uuid4(),
        build_candidate_id=uuid4(),
        status="pass",
    )


def test_silent_ack_gate_partial() -> None:
    r = _report()
    bc = {"_kmbl_compliance": {"silent_acknowledgment": True}}
    out = apply_cool_lane_silent_acknowledgment_gate(r, build_candidate=bc)
    assert out.status == "partial"
    assert out.metrics_json.get("cool_lane_silent_acknowledgment") is True


def test_silent_ack_gate_noop_when_acknowledged() -> None:
    r = _report()
    bc = {"_kmbl_compliance": {"acknowledged": True}}
    out = apply_cool_lane_silent_acknowledgment_gate(r, build_candidate=bc)
    assert out.status == "pass"


def test_invalid_ack_gate_partial() -> None:
    r = _report()
    bc = {
        "_kmbl_compliance": {
            "invalid_execution_acknowledgment_status": True,
            "reason": "bad status",
        },
    }
    out = apply_cool_lane_execution_acknowledgment_gates(r, build_candidate=bc)
    assert out.status == "partial"
    assert out.metrics_json.get("cool_lane_invalid_execution_acknowledgment_status") is True
