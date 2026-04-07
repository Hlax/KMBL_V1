from __future__ import annotations

from uuid import uuid4

from kmbl_orchestrator.domain import EvaluationReportRecord
from kmbl_orchestrator.runtime.interactive_lane_evaluator_gate import (
    LANE_MIX_MISMATCH_CODE,
    LITERAL_REUSE_REGRESSION_CODE,
    WEAK_MEDIA_TRANSFORMATION_CODE,
    apply_interactive_lane_evaluator_gate,
)


def _report() -> EvaluationReportRecord:
    return EvaluationReportRecord(
        evaluation_report_id=uuid4(),
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        evaluator_invocation_id=uuid4(),
        build_candidate_id=uuid4(),
        status="pass",
        summary="ok",
        issues_json=[],
        metrics_json={"_iteration_hint": 1},
        artifacts_json=[],
    )


def test_lane_mix_mismatch_flagged() -> None:
    report = _report()
    bs = {
        "type": "interactive_frontend_app_v1",
        "execution_contract": {
            "lane_mix": {
                "primary_lane": "spatial_gallery",
                "secondary_lanes": ["editorial_story"],
            }
        },
    }
    bc = {
        "_kmbl_iteration_hint": 1,
        "artifact_outputs": [
            {"path": "component/preview/index.html", "content": "<html><body><p>flat text</p></body></html>"}
        ],
    }
    out = apply_interactive_lane_evaluator_gate(
        report,
        build_spec=bs,
        event_input={"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
        build_candidate=bc,
    )
    codes = [i.get("code") for i in out.issues_json if isinstance(i, dict)]
    assert LANE_MIX_MISMATCH_CODE in codes


def test_literal_reuse_regression_flagged() -> None:
    report = _report()
    bs = {
        "type": "interactive_frontend_app_v1",
        "execution_contract": {
            "source_transformation_policy": {
                "literal_source_needles": ["Selected Work", "About Me", "Contact"],
            }
        },
    }
    bc = {
        "_kmbl_iteration_hint": 1,
        "artifact_outputs": [
            {
                "path": "component/preview/index.html",
                "content": "<h2>Selected Work</h2><h2>About Me</h2><h2>Contact</h2>",
            }
        ],
    }
    out = apply_interactive_lane_evaluator_gate(
        report,
        build_spec=bs,
        event_input={"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
        build_candidate=bc,
    )
    codes = [i.get("code") for i in out.issues_json if isinstance(i, dict)]
    assert LITERAL_REUSE_REGRESSION_CODE in codes


def test_weak_media_transformation_flagged() -> None:
    report = _report()
    bs = {
        "type": "interactive_frontend_app_v1",
        "execution_contract": {
            "canvas_system": {
                "media_modes": ["image", "video"],
            }
        },
    }
    bc = {
        "_kmbl_iteration_hint": 1,
        "artifact_outputs": [
            {"path": "component/preview/index.html", "content": "<main><h1>No media</h1></main>"}
        ],
    }
    out = apply_interactive_lane_evaluator_gate(
        report,
        build_spec=bs,
        event_input={"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
        build_candidate=bc,
    )
    codes = [i.get("code") for i in out.issues_json if isinstance(i, dict)]
    assert WEAK_MEDIA_TRANSFORMATION_CODE in codes


def test_lane_mix_uses_scene_manifest_when_present() -> None:
    report = _report()
    bs = {
        "type": "interactive_frontend_app_v1",
        "execution_contract": {
            "lane_mix": {
                "primary_lane": "spatial_gallery",
                "secondary_lanes": ["editorial_story"],
            }
        },
    }
    bc = {
        "_kmbl_iteration_hint": 1,
        "artifact_outputs": [
            {"path": "component/preview/index.html", "content": "<html><body><p>minimal</p></body></html>"}
        ],
        "kmbl_build_candidate_summary_v1": {
            "kmbl_scene_manifest_v1": {
                "lane_mix": {
                    "primary_lane": "spatial_gallery",
                    "secondary_lanes": ["editorial_story"],
                },
                "canvas_model": {"zone_model": "multi_zone"},
            }
        },
    }
    out = apply_interactive_lane_evaluator_gate(
        report,
        build_spec=bs,
        event_input={"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
        build_candidate=bc,
    )
    codes = [i.get("code") for i in out.issues_json if isinstance(i, dict)]
    assert LANE_MIX_MISMATCH_CODE not in codes
