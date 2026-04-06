"""Orchestrator artifact inspection summary v2 (canonical, deterministic)."""

from __future__ import annotations

from kmbl_orchestrator.contracts.role_inputs import validate_role_input
from kmbl_orchestrator.runtime.artifact_inspector_v2 import build_build_candidate_summary_v2


def _arts() -> list[dict]:
    return [
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/index.html",
            "language": "html",
            "content": "<!DOCTYPE html><html><body><canvas></canvas><script src=three></script></body></html>",
        },
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/main.js",
            "language": "js",
            "content": "import * as THREE from 'three';",
        },
    ]


def test_v2_canonical_source_and_artifact_first_flags() -> None:
    bs = {"type": "interactive_frontend_app_v1", "experience_mode": "flat_standard"}
    ei = {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}
    raw = {
        "workspace_manifest_v1": {
            "files": [{"path": "component/preview/index.html"}, {"path": "component/preview/main.js"}]
        }
    }
    s2 = build_build_candidate_summary_v2(
        _arts(),
        build_spec=bs,
        event_input=ei,
        generator_raw=raw,
    )
    assert s2["summary_version"] == 2
    assert s2["canonical_source"] == "orchestrator_artifact_inspection_v2"
    assert s2["artifact_first"]["slim_model_payload_default"] is True
    assert "component/preview/index.html" in s2["artifact_first"]["generator_manifest_paths"]


def test_v2_not_only_generator_notes() -> None:
    s2 = build_build_candidate_summary_v2(
        _arts(),
        build_spec={"type": "interactive_frontend_app_v1"},
        event_input={"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
        generator_notes="I built a rocket ship",
    )
    assert s2["libraries_detected"]  # from real content
    assert s2["artifact_first"]["generator_self_summary_is_unverified"] is True


def test_evaluator_contract_accepts_summary_v2() -> None:
    s2 = build_build_candidate_summary_v2(
        _arts(),
        build_spec={"type": "interactive_frontend_app_v1"},
        event_input={"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
    )
    out = validate_role_input(
        "evaluator",
        {
            "thread_id": "t",
            "build_candidate": {
                "artifact_outputs": [],
                "kmbl_build_candidate_summary_v2": s2,
            },
            "success_criteria": [],
            "evaluation_targets": [],
            "iteration_hint": 0,
            "kmbl_build_candidate_summary_v2": s2,
        },
    )
    assert out["kmbl_build_candidate_summary_v2"]["summary_version"] == 2


def test_generator_contract_accepts_prior_summary_v2() -> None:
    s2 = build_build_candidate_summary_v2(
        _arts(),
        build_spec={"type": "interactive_frontend_app_v1"},
        event_input={"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
    )
    out = validate_role_input(
        "generator",
        {
            "thread_id": "t",
            "build_spec": {"type": "interactive_frontend_app_v1"},
            "kmbl_prior_build_candidate_summary_v2": s2,
            "kmbl_execution_contract": {},
            "surface_type": "static_html",
            "cool_generation_lane_active": False,
            "event_input": {},
        },
    )
    assert out["kmbl_prior_build_candidate_summary_v2"]["summary_version"] == 2
