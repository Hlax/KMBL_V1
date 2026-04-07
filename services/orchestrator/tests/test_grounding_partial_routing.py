"""
Tests for the grounding-partial vs quality-partial routing distinction.

Covers:
    R1  Quality partial → compute_evaluator_decision returns iterate (unchanged)
    R2  Grounding-only partial → is_grounding_only_partial flag detected
    R3  Evaluator report clearly distinguishes grounding_only_partial in metrics
    R4  iteration_plan strips grounding issue from issue_count for grounding-only partial
    R5  iteration_plan strips grounding issue but keeps real issues for mixed partial
    R6  sanitize_feedback_for_generator removes grounding issue code
    R7  sanitize_feedback_for_generator does not mutate quality-only feedback
    R8  sanitize_feedback_for_generator handles None / empty / no-issue cases
    R9  decision_router reroutes grounding-only partial iterate→stage
    R10 decision_router does NOT reroute quality partial
    R11 generator feedback has no grounding issue when grounding-only
    R12 generator feedback preserves real issues for mixed partial
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from kmbl_orchestrator.graph.helpers import compute_evaluator_decision
from kmbl_orchestrator.runtime.demo_preview_grounding import (
    GROUNDING_ISSUE_CODE,
    is_grounding_only_partial,
    sanitize_feedback_for_generator,
)
from kmbl_orchestrator.runtime.iteration_plan import build_iteration_plan_for_generator


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _grounding_issue() -> dict:
    return {
        "code": GROUNDING_ISSUE_CODE,
        "message": "Adjusted pass→partial: demo/public mode requires a browser-reachable preview.",
    }


def _quality_issue(code: str = "layout_overflow") -> dict:
    return {
        "code": code,
        "category": "visual",
        "message": "Hero section overflows on mobile.",
    }


def _quality_partial_report(*extra_issues: dict) -> dict:
    """Evaluation report representing a genuine quality partial."""
    return {
        "status": "partial",
        "summary": "Layout has some issues",
        "issues": [_quality_issue(), *extra_issues],
        "metrics": {
            "design_rubric": {"design_quality": 3, "originality": 3},
        },
    }


def _grounding_only_partial_report() -> dict:
    """Evaluation report produced by the demo grounding gate on a quality-pass build."""
    return {
        "status": "partial",
        "summary": "Build looks good but preview grounding not verified",
        "issues": [_grounding_issue()],
        "metrics": {
            "grounding_only_partial": True,
            "demo_preview_grounding_pass_adjusted": True,
            "preview_grounding_required": True,
            "preview_grounding_satisfied": False,
            "preview_grounding_fallback_reason": "private_host_blocked_by_gateway_policy",
        },
    }


def _mixed_partial_report() -> dict:
    """Partial that has both a real quality issue AND a grounding issue."""
    return {
        "status": "partial",
        "summary": "Layout issues + preview not verified",
        "issues": [_quality_issue(), _grounding_issue()],
        "metrics": {
            "preview_grounding_required": True,
            "preview_grounding_satisfied": False,
            # grounding_only_partial is False (or absent) because there are real issues too
            "grounding_only_partial": False,
        },
    }


# ---------------------------------------------------------------------------
# R1: Quality partial still routes to iterate from compute_evaluator_decision
# ---------------------------------------------------------------------------


class TestQualityPartialRouting:
    def test_quality_partial_iterates_when_under_max(self) -> None:
        d, r = compute_evaluator_decision("partial", 0, 5)
        assert d == "iterate"
        assert r is None

    def test_quality_partial_stages_at_max(self) -> None:
        d, r = compute_evaluator_decision("partial", 5, 5)
        assert d == "stage"
        assert r is None


# ---------------------------------------------------------------------------
# R2 + R3: grounding_only_partial flag detection
# ---------------------------------------------------------------------------


class TestGroundingOnlyFlag:
    def test_is_grounding_only_partial_true_when_flag_set(self) -> None:
        metrics = {"grounding_only_partial": True}
        assert is_grounding_only_partial(metrics) is True

    def test_is_grounding_only_partial_false_when_absent(self) -> None:
        assert is_grounding_only_partial({}) is False

    def test_is_grounding_only_partial_false_for_quality_partial(self) -> None:
        report = _quality_partial_report()
        assert is_grounding_only_partial(report["metrics"]) is False

    def test_is_grounding_only_partial_true_for_grounding_only_report(self) -> None:
        report = _grounding_only_partial_report()
        assert is_grounding_only_partial(report["metrics"]) is True

    def test_is_grounding_only_partial_false_for_mixed_partial(self) -> None:
        report = _mixed_partial_report()
        assert is_grounding_only_partial(report["metrics"]) is False

    def test_grounding_only_report_has_expected_metrics_fields(self) -> None:
        report = _grounding_only_partial_report()
        m = report["metrics"]
        assert m["grounding_only_partial"] is True
        assert m["demo_preview_grounding_pass_adjusted"] is True
        assert m["preview_grounding_required"] is True
        assert m["preview_grounding_satisfied"] is False


# ---------------------------------------------------------------------------
# R4: iteration_plan strips grounding issue from grounding-only partial
# ---------------------------------------------------------------------------


class TestIterationPlanGroundingOnly:
    def test_grounding_only_issue_count_is_zero(self) -> None:
        report = _grounding_only_partial_report()
        plan = build_iteration_plan_for_generator(report)
        assert plan is not None
        assert plan["issue_count"] == 0

    def test_grounding_only_plan_has_flag(self) -> None:
        report = _grounding_only_partial_report()
        plan = build_iteration_plan_for_generator(report)
        assert plan is not None
        assert plan["grounding_only_partial"] is True

    def test_grounding_only_iteration_strategy_is_refine_not_pivot(self) -> None:
        """With issue_count=0 and no stagnation, strategy should be refine (not pivot)."""
        report = _grounding_only_partial_report()
        plan = build_iteration_plan_for_generator(report)
        assert plan is not None
        # Status is partial with no real issues → should not pivot
        assert plan["iteration_strategy"] == "refine"
        assert plan["pivot_layout_strategy"] is False


# ---------------------------------------------------------------------------
# R5: iteration_plan preserves real issues for mixed partial
# ---------------------------------------------------------------------------


class TestIterationPlanMixedPartial:
    def test_mixed_partial_preserves_quality_issue_count(self) -> None:
        report = _mixed_partial_report()
        plan = build_iteration_plan_for_generator(report)
        assert plan is not None
        # 2 issues total, 1 grounding stripped → 1 quality issue remains
        assert plan["issue_count"] == 1

    def test_mixed_partial_flag_is_false(self) -> None:
        report = _mixed_partial_report()
        plan = build_iteration_plan_for_generator(report)
        assert plan is not None
        assert plan["grounding_only_partial"] is False

    def test_quality_only_partial_issue_count_unchanged(self) -> None:
        report = _quality_partial_report()
        plan = build_iteration_plan_for_generator(report)
        assert plan is not None
        assert plan["issue_count"] == 1  # 1 quality issue, no grounding issue to strip


# ---------------------------------------------------------------------------
# R6 + R7 + R8: sanitize_feedback_for_generator
# ---------------------------------------------------------------------------


class TestSanitizeFeedback:
    def test_removes_grounding_issue_from_grounding_only(self) -> None:
        report = _grounding_only_partial_report()
        result = sanitize_feedback_for_generator(report)
        assert result is not None
        assert result["issues"] == []

    def test_removes_only_grounding_issue_from_mixed(self) -> None:
        report = _mixed_partial_report()
        result = sanitize_feedback_for_generator(report)
        assert result is not None
        assert len(result["issues"]) == 1
        assert result["issues"][0]["code"] == "layout_overflow"

    def test_does_not_mutate_quality_only_feedback(self) -> None:
        report = _quality_partial_report()
        original_issues = list(report["issues"])
        result = sanitize_feedback_for_generator(report)
        # No grounding issue present → same object returned (no copy needed)
        assert result is report
        assert result["issues"] == original_issues

    def test_handles_none_input(self) -> None:
        assert sanitize_feedback_for_generator(None) is None

    def test_handles_feedback_without_issues(self) -> None:
        fb = {"status": "partial", "summary": "something"}
        result = sanitize_feedback_for_generator(fb)
        assert result is fb  # unchanged

    def test_handles_non_dict_issues(self) -> None:
        fb = {"status": "partial", "issues": "not a list"}
        result = sanitize_feedback_for_generator(fb)
        assert result is fb

    def test_handles_multiple_grounding_issues(self) -> None:
        fb = {
            "status": "partial",
            "issues": [_grounding_issue(), _grounding_issue()],
        }
        result = sanitize_feedback_for_generator(fb)
        assert result is not None
        assert result["issues"] == []

    def test_mixed_multiple_real_and_grounding_issues(self) -> None:
        fb = {
            "status": "partial",
            "issues": [
                _quality_issue("a"),
                _grounding_issue(),
                _quality_issue("b"),
            ],
        }
        result = sanitize_feedback_for_generator(fb)
        assert result is not None
        assert len(result["issues"]) == 2
        codes = [i["code"] for i in result["issues"]]
        assert "a" in codes
        assert "b" in codes
        assert GROUNDING_ISSUE_CODE not in codes


# ---------------------------------------------------------------------------
# R9 + R10: decision_router rerouting (lightweight, no DB/LLM)
# ---------------------------------------------------------------------------


class TestDecisionRouterGrounding:
    """Test the rerouting logic in decision_router using mocked dependencies."""

    def _make_state(
        self,
        *,
        status: str,
        metrics: dict,
        iteration: int = 0,
        max_iterations: int = 5,
    ) -> dict[str, Any]:
        gid = str(uuid4())
        tid = str(uuid4())
        return {
            "graph_run_id": gid,
            "thread_id": tid,
            "evaluation_report": {
                "status": status,
                "summary": "test",
                "issues": [],
                "metrics": metrics,
            },
            "iteration_index": iteration,
            "max_iterations": max_iterations,
            "alignment_score_history": [],
            "last_alignment_score": None,
            "retry_direction": None,
            "current_state": {},
        }

    def _make_ctx(self) -> MagicMock:
        ctx = MagicMock()
        ctx.settings.graph_max_iterations_default = 5
        ctx.repo.save_graph_run_event = MagicMock()
        return ctx

    def test_grounding_only_partial_routes_to_stage(self) -> None:
        from kmbl_orchestrator.graph.nodes_pkg.decision import decision_router

        state = self._make_state(
            status="partial",
            metrics={"grounding_only_partial": True, "preview_grounding_fallback_reason": "no_preview"},
            iteration=0,
        )
        ctx = self._make_ctx()

        with patch("kmbl_orchestrator.graph.nodes_pkg.decision.raise_if_interrupt_requested"):
            result = decision_router(ctx, state)

        assert result["decision"] == "stage"

    def test_quality_partial_routes_to_iterate(self) -> None:
        from kmbl_orchestrator.graph.nodes_pkg.decision import decision_router

        state = self._make_state(
            status="partial",
            metrics={},  # no grounding_only_partial flag
            iteration=0,
        )
        ctx = self._make_ctx()

        with patch("kmbl_orchestrator.graph.nodes_pkg.decision.raise_if_interrupt_requested"):
            result = decision_router(ctx, state)

        assert result["decision"] == "iterate"

    def test_grounding_only_partial_at_max_also_stages(self) -> None:
        """Even at max_iterations, grounding-only still stages (it was already going to)."""
        from kmbl_orchestrator.graph.nodes_pkg.decision import decision_router

        state = self._make_state(
            status="partial",
            metrics={"grounding_only_partial": True},
            iteration=5,
            max_iterations=5,
        )
        ctx = self._make_ctx()

        with patch("kmbl_orchestrator.graph.nodes_pkg.decision.raise_if_interrupt_requested"):
            result = decision_router(ctx, state)

        assert result["decision"] == "stage"


# ---------------------------------------------------------------------------
# R11 + R12: generator feedback sanitisation integration
# ---------------------------------------------------------------------------


class TestGeneratorFeedbackContent:
    """Verify grounding issues are absent from what generator receives."""

    def test_grounding_only_feedback_has_empty_issues(self) -> None:
        report = _grounding_only_partial_report()
        sanitized = sanitize_feedback_for_generator(report)
        assert sanitized is not None
        assert sanitized["issues"] == []
        # Status is preserved — generator can still see it was partial
        assert sanitized["status"] == "partial"

    def test_grounding_only_feedback_issue_count_for_iteration_plan(self) -> None:
        """After sanitize → iteration_plan sees issue_count=0 (no actionable items)."""
        report = _grounding_only_partial_report()
        sanitized = sanitize_feedback_for_generator(report)
        plan = build_iteration_plan_for_generator(sanitized)
        assert plan is not None
        assert plan["issue_count"] == 0
        assert plan["grounding_only_partial"] is True

    def test_mixed_feedback_preserves_actionable_issues(self) -> None:
        """For mixed partial, generator receives only the real quality issues."""
        report = _mixed_partial_report()
        sanitized = sanitize_feedback_for_generator(report)
        assert sanitized is not None
        assert len(sanitized["issues"]) == 1
        assert sanitized["issues"][0]["code"] == "layout_overflow"

    def test_mixed_feedback_iteration_plan_has_correct_issue_count(self) -> None:
        report = _mixed_partial_report()
        sanitized = sanitize_feedback_for_generator(report)
        plan = build_iteration_plan_for_generator(sanitized)
        assert plan is not None
        # 1 quality issue remains after grounding issue stripped
        assert plan["issue_count"] == 1
        assert plan["grounding_only_partial"] is False
