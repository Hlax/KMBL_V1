"""Tests for interactive_frontend_app_v1 lane hints and preview-risk scanning."""

from __future__ import annotations

from uuid import uuid4

from kmbl_orchestrator.domain import EvaluationReportRecord


def test_build_interactive_lane_context_keys() -> None:
    from kmbl_orchestrator.runtime.interactive_lane_context import build_interactive_lane_context

    ctx = build_interactive_lane_context(
        {
            "type": "interactive_frontend_app_v1",
            "experience_mode": "webgl_3d_portfolio",
            "execution_contract": {
                "surface_type": "multi_file_static",
                "required_interactions": [{"id": "filter_panel", "mechanism": "js"}],
            },
        },
        {},
    )
    assert ctx["lane"] == "interactive_frontend_app_v1"
    assert ctx["heavy_webgl_product_mode_requested"] is True
    assert "preview_pipeline" in ctx
    assert "evaluator_fairness" in ctx
    assert "filter_panel" in str(ctx["execution_contract_signals"]["required_interactions_preview"])


def test_build_interactive_lane_context_not_heavy_by_default() -> None:
    from kmbl_orchestrator.runtime.interactive_lane_context import build_interactive_lane_context

    ctx = build_interactive_lane_context(
        {"type": "interactive_frontend_app_v1", "experience_mode": "flat_standard"},
        {},
    )
    assert ctx["heavy_webgl_product_mode_requested"] is False


def test_scan_interactive_bundle_preview_risks_finds_relative_import() -> None:
    from kmbl_orchestrator.staging.integrity import scan_interactive_bundle_preview_risks

    risks = scan_interactive_bundle_preview_risks(
        [
            {
                "role": "interactive_frontend_app_v1",
                "file_path": "component/preview/app.js",
                "content": "import { x } from './utils.js';\nconsole.log(x);\n",
            }
        ]
    )
    assert len(risks) >= 1
    assert risks[0]["code"] == "relative_es_module_import"
    assert "utils" in risks[0]["detail"]


def test_validate_role_input_accepts_interactive_lane_fields() -> None:
    from kmbl_orchestrator.contracts.role_inputs import validate_role_input

    g = validate_role_input(
        "generator",
        {
            "thread_id": "t",
            "build_spec": {"type": "interactive_frontend_app_v1"},
            "kmbl_interactive_lane_context": {"lane": "interactive_frontend_app_v1"},
        },
    )
    assert g["kmbl_interactive_lane_context"]["lane"] == "interactive_frontend_app_v1"

    e = validate_role_input(
        "evaluator",
        {
            "thread_id": "t",
            "build_candidate": {},
            "success_criteria": [],
            "evaluation_targets": [],
            "iteration_hint": 0,
            "kmbl_interactive_lane_expectations": {"lane": "interactive_frontend_app_v1"},
        },
    )
    assert e["kmbl_interactive_lane_expectations"]["lane"] == "interactive_frontend_app_v1"


def test_normalize_interactive_build_spec_inplace() -> None:
    from kmbl_orchestrator.contracts.interactive_build_spec_v1 import (
        apply_interactive_build_spec_hardening,
    )

    bs: dict = {"type": "interactive_frontend_app_v1", "title": "t", "steps": []}
    _, meta = apply_interactive_build_spec_hardening(
        bs,
        {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
    )
    assert meta.interactive_vertical is True
    assert "interactive_runtime_tier_defaulted" in meta.fixes
    assert "required_interactions_empty_weak_intent" in meta.fixes
    assert meta.interaction_intent_weak is True
    assert bs["execution_contract"]["interactive_runtime_tier"] == "bounded_preview"
    assert "lane_escalation_hint" in bs["execution_contract"]
    assert meta.fields_missing_before.get("required_interactions") is True


def test_apply_interactive_build_spec_hardening_no_op_for_static() -> None:
    from kmbl_orchestrator.contracts.interactive_build_spec_v1 import (
        apply_interactive_build_spec_hardening,
    )

    bs = {"type": "static_frontend_file_v1", "title": "t", "steps": []}
    out, meta = apply_interactive_build_spec_hardening(bs, {})
    assert out is bs
    assert meta.applied is False
    assert meta.interactive_vertical is False
    assert "execution_contract" not in bs


def test_interactive_execution_contract_pydantic_roundtrip() -> None:
    from kmbl_orchestrator.contracts.interactive_build_spec_v1 import (
        InteractiveExecutionContractV1,
    )

    m = InteractiveExecutionContractV1.model_validate(
        {
            "allowed_libraries": ["GSAP", "three"],
            "required_interactions": [{"id": "x", "mechanism": "js"}],
            "interactive_runtime_tier": "bounded_preview",
        }
    )
    assert m.allowed_libraries == ["gsap", "three"]


def test_planner_validate_single_entrypoint_hardens_interactive_without_manual_step() -> None:
    """Smoke and graph paths rely on validate_role_output_for_persistence to harden first."""
    from kmbl_orchestrator.contracts.persistence_validate import validate_role_output_for_persistence

    raw = {
        "build_spec": {"type": "interactive_frontend_app_v1", "title": "t", "steps": []},
        "constraints": {"canonical_vertical": "interactive_frontend_app_v1"},
        "success_criteria": [],
        "evaluation_targets": [],
    }
    validate_role_output_for_persistence("planner", raw)
    assert "execution_contract" in raw["build_spec"]
    h = raw["_kmbl_planner_metadata"]["interactive_build_spec_hardening"]
    assert h["interactive_vertical"] is True
    assert "interactive_runtime_tier_defaulted" in h["fixes"]


def test_planner_validate_static_vertical_does_not_set_interactive_hardening_metadata() -> None:
    from kmbl_orchestrator.contracts.persistence_validate import validate_role_output_for_persistence

    raw = {
        "build_spec": {"type": "static_frontend_file_v1", "title": "t", "steps": []},
        "constraints": {"canonical_vertical": "static_frontend_file_v1"},
        "success_criteria": [],
        "evaluation_targets": [],
    }
    validate_role_output_for_persistence("planner", raw)
    assert "interactive_build_spec_hardening" not in raw.get("_kmbl_planner_metadata", {})


def test_interactive_heavy_webgl_ambition_and_out_of_scope() -> None:
    from kmbl_orchestrator.contracts.interactive_build_spec_v1 import (
        apply_interactive_build_spec_hardening,
    )

    bs = {
        "type": "interactive_frontend_app_v1",
        "title": "t",
        "steps": [],
        "experience_mode": "webgl_3d_portfolio",
        "execution_contract": {
            "surface_type": "client_router_spa",
            "required_interactions": [{"id": "orbit", "mechanism": "js"}],
        },
    }
    _, meta = apply_interactive_build_spec_hardening(
        bs,
        {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
    )
    assert meta.ambition_profile == "heavy_webgl_ask"
    assert "surface_type_suggests_spa_or_router" in meta.out_of_scope_signals
    assert bs["execution_contract"]["webgl_ambition_ack"]


def test_apply_interactive_lane_evaluator_gate_downgrades_pass_on_evidence_gap() -> None:
    from kmbl_orchestrator.runtime.interactive_lane_evaluator_gate import (
        apply_interactive_lane_evaluator_gate,
    )

    rid = uuid4()
    report = EvaluationReportRecord(
        evaluation_report_id=rid,
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        evaluator_invocation_id=uuid4(),
        build_candidate_id=uuid4(),
        status="pass",
        summary="ok",
        issues_json=[],
        metrics_json={},
        artifacts_json=[],
    )
    bs = {
        "type": "interactive_frontend_app_v1",
        "title": "x",
        "steps": [],
        "execution_contract": {"required_interactions": [{"id": "toggle", "mechanism": "js"}]},
    }
    bc = {
        "artifact_outputs": [
            {
                "role": "interactive_frontend_app_v1",
                "path": "component/preview/index.html",
                "content": "<!DOCTYPE html><html><body><button>x</button></body></html>",
            }
        ]
    }
    out = apply_interactive_lane_evaluator_gate(
        report,
        build_spec=bs,
        event_input={"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
        build_candidate=bc,
    )
    assert out.status == "partial"
    assert "interactive_lane_metrics" in out.metrics_json
    assert out.metrics_json["interactive_lane_metrics"]["planned_required_interactions"] == 1
    codes = [i.get("code") for i in out.issues_json if isinstance(i, dict)]
    assert "interactive_lane_evidence_gap" in codes
    assert "interactive_lane_hollow_affordances" in codes


def test_scan_interactive_bundle_missing_script_evidence() -> None:
    from kmbl_orchestrator.staging.integrity import scan_interactive_bundle_missing_script_evidence

    assert scan_interactive_bundle_missing_script_evidence(
        [
            {
                "role": "interactive_frontend_app_v1",
                "path": "c/p/index.html",
                "content": "<!DOCTYPE html><html><body><p>hi</p></body></html>",
            }
        ]
    ) is not None
    long_js = "x" * 40
    assert scan_interactive_bundle_missing_script_evidence(
        [
            {
                "role": "interactive_frontend_app_v1",
                "path": "c/p/index.html",
                "content": (
                    f"<!DOCTYPE html><html><body><script>document.addEventListener('click',()=>{{"
                    f"var a='{long_js}';}});</script></body></html>"
                ),
            }
        ]
    ) is None
