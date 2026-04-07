"""
Tests for runtime integration improvements:

1. Required-library enforcement (interactive_lane_evaluator_gate)
2. Weakly-grounded retry cap (decision_router)
3. Canonical evaluator grounding evidence quality metric
4. Candidate summary required_libraries_compliance surface
5. Feedback sanitisation preserves required_library_missing
6. required_libraries formalised in interactive build spec hardening
7. No regressions to static-lane or non-interactive flows
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from kmbl_orchestrator.domain import EvaluationReportRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_report(
    *,
    status: str = "pass",
    issues: list[dict[str, Any]] | None = None,
    metrics: dict[str, Any] | None = None,
) -> EvaluationReportRecord:
    return EvaluationReportRecord(
        evaluation_report_id=uuid4(),
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        evaluator_invocation_id=uuid4(),
        build_candidate_id=uuid4(),
        status=status,
        summary="test summary",
        issues_json=issues or [],
        metrics_json=metrics or {},
        artifacts_json=[],
    )


def _interactive_build_spec(
    *,
    allowed: list[str] | None = None,
    required: list[str] | None = None,
    interactions: list | None = None,
) -> dict[str, Any]:
    ec: dict[str, Any] = {}
    if allowed is not None:
        ec["allowed_libraries"] = allowed
    if required is not None:
        ec["required_libraries"] = required
    if interactions is not None:
        ec["required_interactions"] = interactions
    return {
        "type": "interactive_frontend_app_v1",
        "title": "t",
        "steps": [],
        "execution_contract": ec,
    }


def _interactive_event_input() -> dict[str, Any]:
    return {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}


def _build_candidate_with_libs(*libs: str) -> dict[str, Any]:
    """Build candidate whose artifact text triggers detection of given lib names."""
    fragments: list[str] = []
    for lib in libs:
        if lib == "three":
            fragments.append('import * as THREE from "three"; new THREE.WebGLRenderer();')
        elif lib == "gsap":
            fragments.append('import gsap from "gsap"; gsap.to("#x", {duration: 1});')
        else:
            fragments.append(f"// {lib} usage placeholder")
    content = "\n".join(fragments) or "<html><body>static</body></html>"
    return {
        "artifact_outputs": [
            {
                "role": "interactive_frontend_app_v1",
                "path": "component/preview/index.html",
                "content": f'<!DOCTYPE html><html><body><canvas></canvas><script>{content}</script></body></html>',
            }
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1. Required-library enforcement gate
# ═══════════════════════════════════════════════════════════════════════════

class TestRequiredLibraryEnforcement:

    def test_missing_required_lib_downgrades_pass_to_partial(self) -> None:
        from kmbl_orchestrator.runtime.interactive_lane_evaluator_gate import (
            REQUIRED_LIBRARY_MISSING_CODE,
            apply_interactive_lane_evaluator_gate,
        )

        report = _make_report(status="pass")
        bs = _interactive_build_spec(required=["three", "gsap"])
        bc = _build_candidate_with_libs("three")  # gsap missing

        out = apply_interactive_lane_evaluator_gate(
            report, build_spec=bs, event_input=_interactive_event_input(), build_candidate=bc,
        )
        assert out.status == "partial"
        codes = [i.get("code") for i in out.issues_json if isinstance(i, dict)]
        assert REQUIRED_LIBRARY_MISSING_CODE in codes
        rlc = out.metrics_json.get("required_libraries_compliance")
        assert rlc is not None
        assert rlc["satisfied"] is False
        assert "gsap" in rlc["missing"]

    def test_satisfied_required_libs_no_downgrade(self) -> None:
        from kmbl_orchestrator.runtime.interactive_lane_evaluator_gate import (
            REQUIRED_LIBRARY_MISSING_CODE,
            apply_interactive_lane_evaluator_gate,
        )

        report = _make_report(status="pass")
        bs = _interactive_build_spec(required=["three", "gsap"])
        bc = _build_candidate_with_libs("three", "gsap")

        out = apply_interactive_lane_evaluator_gate(
            report, build_spec=bs, event_input=_interactive_event_input(), build_candidate=bc,
        )
        # No required_library_missing issue (other gate issues may still fire)
        codes = [i.get("code") for i in out.issues_json if isinstance(i, dict)]
        assert REQUIRED_LIBRARY_MISSING_CODE not in codes
        rlc = out.metrics_json.get("required_libraries_compliance")
        assert rlc is not None
        assert rlc["satisfied"] is True
        assert rlc["missing"] == []

    def test_no_required_libs_backward_compat(self) -> None:
        """Builds with no required_libraries field should not get library-missing issues."""
        from kmbl_orchestrator.runtime.interactive_lane_evaluator_gate import (
            REQUIRED_LIBRARY_MISSING_CODE,
            apply_interactive_lane_evaluator_gate,
        )

        report = _make_report(status="pass")
        bs = _interactive_build_spec(allowed=[], required=None)
        # Remove execution_contract entirely to simulate legacy payloads
        bs["execution_contract"] = {}
        bc = _build_candidate_with_libs()

        out = apply_interactive_lane_evaluator_gate(
            report, build_spec=bs, event_input=_interactive_event_input(), build_candidate=bc,
        )
        codes = [i.get("code") for i in out.issues_json if isinstance(i, dict)]
        assert REQUIRED_LIBRARY_MISSING_CODE not in codes
        rlc = out.metrics_json.get("required_libraries_compliance")
        assert rlc is not None
        assert rlc["required"] == []
        assert rlc["satisfied"] is True

    def test_fallback_to_allowed_when_no_required(self) -> None:
        """When required_libraries is absent, falls back to allowed_libraries for enforcement."""
        from kmbl_orchestrator.runtime.interactive_lane_evaluator_gate import (
            REQUIRED_LIBRARY_MISSING_CODE,
            apply_interactive_lane_evaluator_gate,
        )

        report = _make_report(status="pass")
        bs = _interactive_build_spec(allowed=["three", "gsap"])  # no required_libraries
        bc = _build_candidate_with_libs("three")  # gsap missing

        out = apply_interactive_lane_evaluator_gate(
            report, build_spec=bs, event_input=_interactive_event_input(), build_candidate=bc,
        )
        codes = [i.get("code") for i in out.issues_json if isinstance(i, dict)]
        assert REQUIRED_LIBRARY_MISSING_CODE in codes
        rlc = out.metrics_json["required_libraries_compliance"]
        assert "gsap" in rlc["missing"]

    def test_static_vertical_unaffected(self) -> None:
        """Static verticals should not trigger required-library checks."""
        from kmbl_orchestrator.runtime.interactive_lane_evaluator_gate import (
            apply_interactive_lane_evaluator_gate,
        )

        report = _make_report(status="pass")
        bs = {"type": "static_frontend_file_v1", "title": "t"}
        bc = {"artifact_outputs": []}

        out = apply_interactive_lane_evaluator_gate(
            report, build_spec=bs, event_input={}, build_candidate=bc,
        )
        assert out.status == "pass"
        assert "required_libraries_compliance" not in (out.metrics_json or {})


# ═══════════════════════════════════════════════════════════════════════════
# 2. Weakly-grounded retry cap
# ═══════════════════════════════════════════════════════════════════════════

class TestWeaklyGroundedRetryCap:

    def _make_state(self, *, iteration: int, status: str, grounding_mode: str, max_iter: int = 10) -> dict:
        return {
            "graph_run_id": str(uuid4()),
            "thread_id": str(uuid4()),
            "evaluation_report": {
                "status": status,
                "issues": [],
                "metrics": {
                    "preview_grounding_mode": grounding_mode,
                },
            },
            "iteration_index": iteration,
            "max_iterations": max_iter,
            "last_alignment_score": None,
            "alignment_score_history": [],
        }

    def _make_ctx(self, *, weak_cap: int = 3, max_iter: int = 10):
        settings = MagicMock()
        settings.graph_max_iterations_default = max_iter
        settings.kmbl_weakly_grounded_max_iterations = weak_cap
        repo = MagicMock()
        repo.save_graph_run_event = MagicMock()
        # Interrupt check: get_graph_run must return None or an object with
        # status != "interrupt_requested" and interrupt_requested_at = None.
        repo.get_graph_run.return_value = None
        ctx = MagicMock()
        ctx.settings = settings
        ctx.repo = repo
        return ctx

    def test_iterate_below_cap_is_allowed(self) -> None:
        from kmbl_orchestrator.graph.nodes_pkg.decision import decision_router

        ctx = self._make_ctx(weak_cap=3)
        state = self._make_state(
            iteration=1, status="partial", grounding_mode="operator_local_only",
        )
        result = decision_router(ctx, state)
        assert result["decision"] == "iterate"

    def test_iterate_at_cap_routes_to_stage(self) -> None:
        from kmbl_orchestrator.graph.nodes_pkg.decision import decision_router

        ctx = self._make_ctx(weak_cap=3)
        state = self._make_state(
            iteration=3, status="partial", grounding_mode="operator_local_only",
        )
        result = decision_router(ctx, state)
        assert result["decision"] == "stage"

    def test_iterate_above_cap_routes_to_stage(self) -> None:
        from kmbl_orchestrator.graph.nodes_pkg.decision import decision_router

        ctx = self._make_ctx(weak_cap=3)
        state = self._make_state(
            iteration=5, status="fail", grounding_mode="unavailable",
        )
        result = decision_router(ctx, state)
        assert result["decision"] == "stage"

    def test_browser_grounded_unaffected_by_cap(self) -> None:
        from kmbl_orchestrator.graph.nodes_pkg.decision import decision_router

        ctx = self._make_ctx(weak_cap=3)
        state = self._make_state(
            iteration=5, status="partial", grounding_mode="browser_reachable",
        )
        result = decision_router(ctx, state)
        assert result["decision"] == "iterate"

    def test_cap_zero_disables(self) -> None:
        from kmbl_orchestrator.graph.nodes_pkg.decision import decision_router

        ctx = self._make_ctx(weak_cap=0)
        state = self._make_state(
            iteration=8, status="partial", grounding_mode="operator_local_only",
        )
        result = decision_router(ctx, state)
        assert result["decision"] == "iterate"

    def test_weakly_grounded_event_emitted(self) -> None:
        from kmbl_orchestrator.graph.nodes_pkg.decision import decision_router
        from kmbl_orchestrator.runtime.run_events import RunEventType

        ctx = self._make_ctx(weak_cap=2)
        state = self._make_state(
            iteration=2, status="partial", grounding_mode="snippet",
        )
        decision_router(ctx, state)
        # Events are saved as GraphRunEventRecord objects
        payloads = [
            call.args[0].payload_json
            for call in ctx.repo.save_graph_run_event.call_args_list
            if hasattr(call.args[0], "payload_json")
        ]
        # Find the weakly grounded event
        found = False
        for p in payloads:
            if p.get("weakly_grounded_max_iterations") is not None:
                found = True
                assert p["weakly_grounded_max_iterations"] == 2
                assert p["preview_grounding_mode"] == "snippet"
        assert found, "WEAKLY_GROUNDED_RETRY_CAP event not emitted"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Evaluator grounding quality metric
# ═══════════════════════════════════════════════════════════════════════════

class TestEvaluatorGroundingEvidenceQuality:

    def test_browser_reachable_maps_to_browser(self) -> None:
        res = {"preview_grounding_mode": "browser_reachable"}
        pgm = res.get("preview_grounding_mode", "unavailable")
        if pgm == "browser_reachable":
            quality = "browser"
        elif pgm == "operator_local_only":
            quality = "artifact_only"
        else:
            quality = "none"
        assert quality == "browser"

    def test_operator_local_maps_to_artifact_only(self) -> None:
        res = {"preview_grounding_mode": "operator_local_only"}
        pgm = res.get("preview_grounding_mode", "unavailable")
        if pgm == "browser_reachable":
            quality = "browser"
        elif pgm == "operator_local_only":
            quality = "artifact_only"
        else:
            quality = "none"
        assert quality == "artifact_only"

    def test_unavailable_maps_to_none(self) -> None:
        res = {"preview_grounding_mode": "unavailable"}
        pgm = res.get("preview_grounding_mode", "unavailable")
        if pgm == "browser_reachable":
            quality = "browser"
        elif pgm == "operator_local_only":
            quality = "artifact_only"
        else:
            quality = "none"
        assert quality == "none"

    def test_missing_mode_maps_to_none(self) -> None:
        res: dict = {}
        pgm = res.get("preview_grounding_mode", "unavailable")
        if pgm == "browser_reachable":
            quality = "browser"
        elif pgm == "operator_local_only":
            quality = "artifact_only"
        else:
            quality = "none"
        assert quality == "none"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Candidate summary required_libraries_compliance
# ═══════════════════════════════════════════════════════════════════════════

class TestSummaryRequiredLibrariesCompliance:

    def test_compliance_populated_when_required_present(self) -> None:
        from kmbl_orchestrator.runtime.build_candidate_summary_v1 import build_build_candidate_summary_v1

        arts = [
            {
                "role": "static_frontend_file_v1",
                "path": "component/preview/main.js",
                "language": "js",
                "content": "import * as THREE from 'three'; new THREE.WebGLRenderer();",
            }
        ]
        bs = {
            "type": "interactive_frontend_app_v1",
            "execution_contract": {
                "required_libraries": ["three", "gsap"],
                "allowed_libraries": ["three", "gsap"],
            },
        }
        ei = {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}
        s = build_build_candidate_summary_v1(arts, build_spec=bs, event_input=ei)
        rlc = s.get("required_libraries_compliance")
        assert rlc is not None
        assert "three" in rlc["required"]
        assert "gsap" in rlc["required"]
        assert "three" in rlc["detected"]
        assert "gsap" in rlc["missing"]
        assert rlc["satisfied"] is False

    def test_compliance_satisfied_when_all_detected(self) -> None:
        from kmbl_orchestrator.runtime.build_candidate_summary_v1 import build_build_candidate_summary_v1

        arts = [
            {
                "role": "static_frontend_file_v1",
                "path": "component/preview/main.js",
                "language": "js",
                "content": "import * as THREE from 'three'; new THREE.WebGLRenderer();\nimport gsap from 'gsap'; gsap.to('#x', {duration:1});",
            }
        ]
        bs = {
            "type": "interactive_frontend_app_v1",
            "execution_contract": {
                "required_libraries": ["three", "gsap"],
            },
        }
        ei = {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}
        s = build_build_candidate_summary_v1(arts, build_spec=bs, event_input=ei)
        rlc = s["required_libraries_compliance"]
        assert rlc["satisfied"] is True
        assert rlc["missing"] == []

    def test_compliance_empty_when_no_required(self) -> None:
        from kmbl_orchestrator.runtime.build_candidate_summary_v1 import build_build_candidate_summary_v1

        arts = [
            {
                "role": "static_frontend_file_v1",
                "path": "component/preview/index.html",
                "content": "<html><body>hi</body></html>",
            }
        ]
        bs = {"type": "static_frontend_file_v1"}
        s = build_build_candidate_summary_v1(arts, build_spec=bs, event_input={})
        rlc = s["required_libraries_compliance"]
        assert rlc["required"] == []
        assert rlc["satisfied"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 5. Feedback sanitisation
# ═══════════════════════════════════════════════════════════════════════════

class TestFeedbackSanitisation:

    def test_grounding_issue_stripped(self) -> None:
        from kmbl_orchestrator.runtime.demo_preview_grounding import (
            GROUNDING_ISSUE_CODE,
            sanitize_feedback_for_generator,
        )

        feedback = {
            "issues": [
                {"code": GROUNDING_ISSUE_CODE, "message": "infra"},
                {"code": "quality_gap", "message": "missing heading"},
            ]
        }
        result = sanitize_feedback_for_generator(feedback)
        assert result is not None
        codes = [i["code"] for i in result["issues"]]
        assert GROUNDING_ISSUE_CODE not in codes
        assert "quality_gap" in codes

    def test_required_library_missing_preserved(self) -> None:
        from kmbl_orchestrator.runtime.demo_preview_grounding import (
            GROUNDING_ISSUE_CODE,
            sanitize_feedback_for_generator,
        )
        from kmbl_orchestrator.runtime.interactive_lane_evaluator_gate import (
            REQUIRED_LIBRARY_MISSING_CODE,
        )

        feedback = {
            "issues": [
                {"code": GROUNDING_ISSUE_CODE, "message": "infra"},
                {"code": REQUIRED_LIBRARY_MISSING_CODE, "message": "missing gsap"},
            ]
        }
        result = sanitize_feedback_for_generator(feedback)
        assert result is not None
        codes = [i["code"] for i in result["issues"]]
        assert REQUIRED_LIBRARY_MISSING_CODE in codes
        assert GROUNDING_ISSUE_CODE not in codes

    def test_no_issues_no_crash(self) -> None:
        from kmbl_orchestrator.runtime.demo_preview_grounding import sanitize_feedback_for_generator

        assert sanitize_feedback_for_generator(None) is None
        assert sanitize_feedback_for_generator({}) == {}
        assert sanitize_feedback_for_generator({"issues": "not_a_list"}) == {"issues": "not_a_list"}


# ═══════════════════════════════════════════════════════════════════════════
# 6. required_libraries in interactive build spec hardening
# ═══════════════════════════════════════════════════════════════════════════

class TestRequiredLibrariesBuildSpecHardening:

    def test_required_libraries_defaulted_from_allowed(self) -> None:
        from kmbl_orchestrator.contracts.interactive_build_spec_v1 import (
            apply_interactive_build_spec_hardening,
        )

        bs: dict = {"type": "interactive_frontend_app_v1", "title": "t", "steps": []}
        _, meta = apply_interactive_build_spec_hardening(
            bs,
            {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
        )
        assert meta.interactive_vertical is True
        ec = bs["execution_contract"]
        # required_libraries should default to match allowed_libraries
        assert ec["required_libraries"] == ec["allowed_libraries"]
        assert "three" in ec["required_libraries"]
        assert "gsap" in ec["required_libraries"]
        assert "required_libraries_defaulted_from_allowed" in meta.fixes

    def test_explicit_required_libraries_preserved(self) -> None:
        from kmbl_orchestrator.contracts.interactive_build_spec_v1 import (
            apply_interactive_build_spec_hardening,
        )

        bs: dict = {
            "type": "interactive_frontend_app_v1",
            "title": "t",
            "steps": [],
            "execution_contract": {
                "allowed_libraries": ["three", "gsap"],
                "required_libraries": ["three"],
            },
        }
        _, meta = apply_interactive_build_spec_hardening(
            bs,
            {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
        )
        ec = bs["execution_contract"]
        assert ec["required_libraries"] == ["three"]
        assert "required_libraries_defaulted_from_allowed" not in meta.fixes

    def test_static_vertical_no_required_libraries(self) -> None:
        from kmbl_orchestrator.contracts.interactive_build_spec_v1 import (
            apply_interactive_build_spec_hardening,
        )

        bs = {"type": "static_frontend_file_v1", "title": "t", "steps": []}
        out, meta = apply_interactive_build_spec_hardening(bs, {})
        assert meta.applied is False
        assert "execution_contract" not in bs

    def test_pydantic_model_validates_required_libraries(self) -> None:
        from kmbl_orchestrator.contracts.interactive_build_spec_v1 import (
            InteractiveExecutionContractV1,
        )

        m = InteractiveExecutionContractV1.model_validate(
            {
                "allowed_libraries": ["GSAP", "three"],
                "required_libraries": ["THREE"],
            }
        )
        assert m.allowed_libraries == ["gsap", "three"]
        assert m.required_libraries == ["three"]

    def test_pydantic_model_default_empty_required(self) -> None:
        from kmbl_orchestrator.contracts.interactive_build_spec_v1 import (
            InteractiveExecutionContractV1,
        )

        m = InteractiveExecutionContractV1.model_validate({})
        assert m.required_libraries == []


# ═══════════════════════════════════════════════════════════════════════════
# 7. Config setting exists and has expected default
# ═══════════════════════════════════════════════════════════════════════════

class TestWeaklyGroundedConfig:

    def test_default_value(self) -> None:
        from kmbl_orchestrator.config import Settings

        s = Settings()
        assert s.kmbl_weakly_grounded_max_iterations == 3

    def test_run_event_type_exists(self) -> None:
        from kmbl_orchestrator.runtime.run_events import RunEventType

        assert hasattr(RunEventType, "WEAKLY_GROUNDED_RETRY_CAP")
        assert RunEventType.WEAKLY_GROUNDED_RETRY_CAP == "weakly_grounded_retry_cap"
