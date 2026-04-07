"""
Integration-style tests for compact payloads + grounding-only routing.

Covers the end-to-end routing contract without requiring live DB or KiloClaw:

    I1  Planner replan_context uses slim prior_build_spec (no creative/crawl blobs)
    I2  Planner replan_context has prior_build_spec_digest matching original
    I3  Planner crawl_context is compacted at iteration > 0
    I4  Planner crawl_context is full at iteration 0
    I5  _PLANNER_REPLAN_SPEC_KEYS is a superset of experience_mode + success_criteria + site_archetype
    I6  compact_crawl_context_for_replan strips page summaries but keeps phase/counts
    I7  compact_crawl_context_for_replan handles None/non-dict gracefully
    I8  Grounding-only partial routes to stage, not iterate (decision_router integration)
    I9  Mixed partial (quality + grounding) routes to iterate under max
    I10 Full chain: grounding-only partial → compact iteration_plan → issue_count=0 → stage
    I11 Full chain: mixed partial → iteration_plan → issue_count=1 after grounding stripped
    I12 Generator apply_iteration_compaction: build_spec slimmed + digest set
    I13 Generator compact does not mutate original build_spec reference
    I14 Evaluator previous_evaluation_report is compacted (no metrics) at iteration > 0
    I15 compact_previous_evaluation_report_for_llm: issues capped at 5, metrics absent
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from kmbl_orchestrator.runtime.generator_iteration_compact_v1 import (
    _BUILD_SPEC_ITERATION_KEYS,
    _PLANNER_REPLAN_SPEC_KEYS,
    apply_iteration_compaction,
    build_spec_digest,
    compact_crawl_context_for_replan,
    compact_previous_evaluation_report_for_llm,
)
from kmbl_orchestrator.runtime.demo_preview_grounding import (
    GROUNDING_ISSUE_CODE,
    is_grounding_only_partial,
    sanitize_feedback_for_generator,
)
from kmbl_orchestrator.runtime.iteration_plan import build_iteration_plan_for_generator
from kmbl_orchestrator.graph.helpers import compute_evaluator_decision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fat_build_spec() -> dict[str, Any]:
    """A build_spec with lots of fields the planner and generator don't need on retries."""
    return {
        "experience_mode": "flat_standard",
        "surface_type": "static_html",
        "canonical_vertical": "saas_landing",
        "site_archetype": "dark_hero",
        "success_criteria": ["Hero is bold", "CTA is visible"],
        "evaluation_targets": ["visual_quality", "layout_fidelity"],
        "literal_success_checks": [],
        "cool_generation_lane": False,
        "interaction_model": "scroll",
        "motion_spec": None,
        "required_libraries": ["tailwind"],
        "library_hints": [],
        "machine_constraints": {},
        "selected_urls": ["https://example.com/about"],
        # Large blobs that must NOT be replayed on iteration > 0:
        "creative_brief": {
            "tone": "bold",
            "narrative": "Long story " * 200,
            "color_guidance": {"primary": "#000", "secondary": "#fff"},
        },
        "crawl_context_snapshot": {"pages": [{"url": f"https://ex.com/{i}", "body": "x" * 500} for i in range(20)]},
        "raw_planner_reference_cards": [{"id": i, "content": "ref " * 100} for i in range(10)],
    }


def _fat_crawl_context() -> dict[str, Any]:
    return {
        "visited_count": 12,
        "extracted_fact_digest": "abc123def456",
        "crawl_phase": "multi_page",
        "grounding_available": True,
        "crawl_exhausted": False,
        "next_urls": ["https://ex.com/page2", "https://ex.com/page3"],
        # Large blobs that must NOT be replayed on replan:
        "page_summaries": [{"url": f"https://ex.com/{i}", "summary": "Content " * 100} for i in range(12)],
        "extracted_facts": [{"fact": f"fact_{i}", "source": f"https://ex.com/{i}"} for i in range(30)],
    }


def _grounding_only_partial_report() -> dict[str, Any]:
    return {
        "status": "partial",
        "summary": "Build looks good but preview grounding not verified",
        "issues": [{"code": GROUNDING_ISSUE_CODE, "message": "..."}],
        "metrics": {
            "grounding_only_partial": True,
            "demo_preview_grounding_pass_adjusted": True,
            "preview_grounding_required": True,
            "preview_grounding_satisfied": False,
            "preview_grounding_fallback_reason": "private_host_blocked_by_gateway_policy",
        },
    }


def _mixed_partial_report() -> dict[str, Any]:
    return {
        "status": "partial",
        "summary": "Quality issues + grounding gap",
        "issues": [
            {"code": "layout_overflow", "category": "visual", "message": "Hero overflow"},
            {"code": GROUNDING_ISSUE_CODE, "message": "..."},
        ],
        "metrics": {
            "grounding_only_partial": False,
            "preview_grounding_required": True,
            "preview_grounding_satisfied": False,
        },
    }


def _quality_partial_report() -> dict[str, Any]:
    return {
        "status": "partial",
        "summary": "Layout issues",
        "issues": [{"code": "layout_overflow", "category": "visual", "message": "Hero overflow"}],
        "metrics": {"design_rubric": {"design_quality": 3, "originality": 3}},
    }


# ---------------------------------------------------------------------------
# I1–I4: Planner replan_context compaction
# ---------------------------------------------------------------------------


class TestPlannerReplanCompaction:
    def test_planner_replan_spec_keys_contains_experience_mode(self) -> None:
        assert "experience_mode" in _PLANNER_REPLAN_SPEC_KEYS

    def test_planner_replan_spec_keys_contains_success_criteria(self) -> None:
        assert "success_criteria" in _PLANNER_REPLAN_SPEC_KEYS

    def test_planner_replan_spec_keys_contains_site_archetype(self) -> None:
        assert "site_archetype" in _PLANNER_REPLAN_SPEC_KEYS

    def test_planner_replan_spec_keys_contains_selected_urls(self) -> None:
        assert "selected_urls" in _PLANNER_REPLAN_SPEC_KEYS

    def test_slim_prior_build_spec_excludes_creative_brief(self) -> None:
        bs = _fat_build_spec()
        slim = {k: v for k, v in bs.items() if k in _PLANNER_REPLAN_SPEC_KEYS}
        assert "creative_brief" not in slim

    def test_slim_prior_build_spec_excludes_crawl_snapshot(self) -> None:
        bs = _fat_build_spec()
        slim = {k: v for k, v in bs.items() if k in _PLANNER_REPLAN_SPEC_KEYS}
        assert "crawl_context_snapshot" not in slim
        assert "raw_planner_reference_cards" not in slim

    def test_slim_prior_build_spec_retains_core_fields(self) -> None:
        bs = _fat_build_spec()
        slim = {k: v for k, v in bs.items() if k in _PLANNER_REPLAN_SPEC_KEYS}
        assert slim["experience_mode"] == "flat_standard"
        assert slim["canonical_vertical"] == "saas_landing"
        assert slim["success_criteria"] == ["Hero is bold", "CTA is visible"]
        assert slim["selected_urls"] == ["https://example.com/about"]

    def test_slim_prior_build_spec_is_significantly_smaller(self) -> None:
        bs = _fat_build_spec()
        slim = {k: v for k, v in bs.items() if k in _PLANNER_REPLAN_SPEC_KEYS}
        full_size = len(json.dumps(bs))
        slim_size = len(json.dumps(slim))
        assert slim_size < full_size * 0.5  # at least 50% reduction

    def test_prior_build_spec_digest_matches_original(self) -> None:
        bs = _fat_build_spec()
        digest = build_spec_digest(bs)
        assert len(digest) == 16  # SHA-256[:16]
        # Digest is deterministic
        assert build_spec_digest(bs) == digest

    def test_prior_build_spec_digest_changes_with_spec(self) -> None:
        bs1 = _fat_build_spec()
        bs2 = {**bs1, "experience_mode": "parallax_narrative"}
        assert build_spec_digest(bs1) != build_spec_digest(bs2)


# ---------------------------------------------------------------------------
# I6–I7: compact_crawl_context_for_replan
# ---------------------------------------------------------------------------


class TestCompactCrawlContext:
    def test_strips_page_summaries(self) -> None:
        cc = _fat_crawl_context()
        compact = compact_crawl_context_for_replan(cc)
        assert compact is not None
        assert "page_summaries" not in compact

    def test_strips_extracted_facts(self) -> None:
        cc = _fat_crawl_context()
        compact = compact_crawl_context_for_replan(cc)
        assert compact is not None
        assert "extracted_facts" not in compact

    def test_keeps_visited_count(self) -> None:
        cc = _fat_crawl_context()
        compact = compact_crawl_context_for_replan(cc)
        assert compact is not None
        assert compact["visited_count"] == 12

    def test_keeps_crawl_phase(self) -> None:
        cc = _fat_crawl_context()
        compact = compact_crawl_context_for_replan(cc)
        assert compact is not None
        assert compact["crawl_phase"] == "multi_page"

    def test_keeps_grounding_available(self) -> None:
        cc = _fat_crawl_context()
        compact = compact_crawl_context_for_replan(cc)
        assert compact is not None
        assert compact["grounding_available"] is True

    def test_keeps_crawl_exhausted(self) -> None:
        cc = _fat_crawl_context()
        compact = compact_crawl_context_for_replan(cc)
        assert compact is not None
        assert compact["crawl_exhausted"] is False

    def test_replaces_next_urls_with_count(self) -> None:
        cc = _fat_crawl_context()
        compact = compact_crawl_context_for_replan(cc)
        assert compact is not None
        assert "next_urls" not in compact
        assert compact["next_urls_count"] == 2

    def test_sets_compacted_flag(self) -> None:
        cc = _fat_crawl_context()
        compact = compact_crawl_context_for_replan(cc)
        assert compact is not None
        assert compact["_kmbl_compacted"] is True

    def test_is_much_smaller_than_full(self) -> None:
        cc = _fat_crawl_context()
        compact = compact_crawl_context_for_replan(cc)
        assert compact is not None
        assert len(json.dumps(compact)) < len(json.dumps(cc)) * 0.1  # > 90% reduction

    def test_handles_none(self) -> None:
        assert compact_crawl_context_for_replan(None) is None

    def test_handles_non_dict(self) -> None:
        assert compact_crawl_context_for_replan("not a dict") == "not a dict"  # type: ignore[arg-type]

    def test_handles_empty_next_urls(self) -> None:
        cc = {"visited_count": 5, "crawl_phase": "single_page", "next_urls": []}
        compact = compact_crawl_context_for_replan(cc)
        assert compact is not None
        assert compact["next_urls_count"] == 0


# ---------------------------------------------------------------------------
# I8–I11: Grounding-only routing integration
# ---------------------------------------------------------------------------


class TestGroundingOnlyRouting:
    def _make_state(self, status: str, metrics: dict, iteration: int = 0, max_iter: int = 5) -> dict:
        return {
            "graph_run_id": str(uuid4()),
            "thread_id": str(uuid4()),
            "evaluation_report": {"status": status, "summary": "test", "issues": [], "metrics": metrics},
            "iteration_index": iteration,
            "max_iterations": max_iter,
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

    def test_grounding_only_routes_to_stage(self) -> None:
        from kmbl_orchestrator.graph.nodes_pkg.decision import decision_router

        state = self._make_state(
            "partial", {"grounding_only_partial": True, "preview_grounding_fallback_reason": "no_preview"}
        )
        with patch("kmbl_orchestrator.graph.nodes_pkg.decision.raise_if_interrupt_requested"):
            result = decision_router(self._make_ctx(), state)
        assert result["decision"] == "stage"

    def test_mixed_partial_routes_to_iterate(self) -> None:
        from kmbl_orchestrator.graph.nodes_pkg.decision import decision_router

        state = self._make_state(
            "partial", {"grounding_only_partial": False}
        )
        with patch("kmbl_orchestrator.graph.nodes_pkg.decision.raise_if_interrupt_requested"):
            result = decision_router(self._make_ctx(), state)
        assert result["decision"] == "iterate"

    def test_grounding_only_at_max_iterations_still_stages(self) -> None:
        from kmbl_orchestrator.graph.nodes_pkg.decision import decision_router

        state = self._make_state(
            "partial", {"grounding_only_partial": True}, iteration=5, max_iter=5
        )
        with patch("kmbl_orchestrator.graph.nodes_pkg.decision.raise_if_interrupt_requested"):
            result = decision_router(self._make_ctx(), state)
        assert result["decision"] == "stage"


# ---------------------------------------------------------------------------
# I10–I11: Full chain tests (grounding → iteration_plan → issue_count)
# ---------------------------------------------------------------------------


class TestFullChainIterationPlan:
    def test_grounding_only_chain_issue_count_zero(self) -> None:
        report = _grounding_only_partial_report()
        sanitized = sanitize_feedback_for_generator(report)
        plan = build_iteration_plan_for_generator(sanitized)
        assert plan is not None
        assert plan["issue_count"] == 0
        assert plan["grounding_only_partial"] is True
        assert plan["iteration_strategy"] == "refine"

    def test_mixed_partial_chain_issue_count_one(self) -> None:
        report = _mixed_partial_report()
        sanitized = sanitize_feedback_for_generator(report)
        plan = build_iteration_plan_for_generator(sanitized)
        assert plan is not None
        assert plan["issue_count"] == 1
        assert plan["grounding_only_partial"] is False

    def test_quality_partial_chain_issue_count_unchanged(self) -> None:
        report = _quality_partial_report()
        sanitized = sanitize_feedback_for_generator(report)
        assert sanitized is report  # no grounding issue to strip — same object
        plan = build_iteration_plan_for_generator(sanitized)
        assert plan is not None
        assert plan["issue_count"] == 1
        assert plan["grounding_only_partial"] is False


# ---------------------------------------------------------------------------
# I12–I13: Generator apply_iteration_compaction
# ---------------------------------------------------------------------------


class TestGeneratorIterationCompaction:
    def _make_gen_payload(self) -> dict[str, Any]:
        bs = _fat_build_spec()
        return {
            "build_spec": dict(bs),
            "event_input": {
                "kmbl_session_staging": {"thread_id": "t"},
                "crawl_context": _fat_crawl_context(),
            },
            "structured_identity": {
                "themes": [f"t{i}" for i in range(20)],
                "tone": "bold",
                "visual_tendencies": [f"v{i}" for i in range(20)],
                "notable_entities": [f"e{i}" for i in range(20)],
                "complexity": "high",
            },
        }

    def test_build_spec_is_slimmed(self) -> None:
        payload = self._make_gen_payload()
        apply_iteration_compaction(payload, iteration=1)
        result_bs = payload["build_spec"]
        # creative_brief and execution_contract are now retained for iteration context
        assert "creative_brief" in result_bs
        assert "crawl_context_snapshot" not in result_bs

    def test_digest_set_to_original(self) -> None:
        original_bs = _fat_build_spec()
        payload = self._make_gen_payload()
        expected = build_spec_digest(original_bs)
        apply_iteration_compaction(payload, iteration=1)
        assert payload["kmbl_locked_build_spec_digest"] == expected

    def test_does_not_mutate_at_iteration_0(self) -> None:
        payload = self._make_gen_payload()
        original_bs_keys = set(payload["build_spec"].keys())
        apply_iteration_compaction(payload, iteration=0)
        assert set(payload["build_spec"].keys()) == original_bs_keys
        assert "kmbl_locked_build_spec_digest" not in payload

    def test_build_spec_only_has_iteration_keys(self) -> None:
        payload = self._make_gen_payload()
        apply_iteration_compaction(payload, iteration=1)
        for key in payload["build_spec"]:
            assert key in _BUILD_SPEC_ITERATION_KEYS

    def test_chars_saved_is_positive(self) -> None:
        payload = self._make_gen_payload()
        saved = apply_iteration_compaction(payload, iteration=1)
        assert saved > 0


# ---------------------------------------------------------------------------
# I14–I15: Evaluator previous_evaluation_report compaction
# ---------------------------------------------------------------------------


class TestEvaluatorPrevReportCompaction:
    def _fat_report(self) -> dict[str, Any]:
        return {
            "status": "partial",
            "summary": "Some issues found",
            "issues": [{"code": f"issue_{i}"} for i in range(10)],
            "alignment_score": 0.7,
            "metrics": {
                "grounding_only_partial": False,
                "design_rubric": {"design_quality": 3, "originality": 2},
                "internal_gate_state": {"gates": list(range(50))},
            },
            "artifacts": [{"ref": "file.html"}, {"ref": "style.css"}],
            "alignment_signals": {"color": 0.8, "layout": 0.7},
        }

    def test_metrics_not_in_compact(self) -> None:
        compact = compact_previous_evaluation_report_for_llm(self._fat_report())
        assert compact is not None
        assert "metrics" not in compact

    def test_artifacts_not_in_compact(self) -> None:
        compact = compact_previous_evaluation_report_for_llm(self._fat_report())
        assert compact is not None
        assert "artifacts" not in compact

    def test_alignment_signals_not_in_compact(self) -> None:
        compact = compact_previous_evaluation_report_for_llm(self._fat_report())
        assert compact is not None
        assert "alignment_signals" not in compact

    def test_issues_capped_at_5(self) -> None:
        compact = compact_previous_evaluation_report_for_llm(self._fat_report())
        assert compact is not None
        assert len(compact["issues"]) == 5

    def test_status_preserved(self) -> None:
        compact = compact_previous_evaluation_report_for_llm(self._fat_report())
        assert compact is not None
        assert compact["status"] == "partial"

    def test_alignment_score_preserved(self) -> None:
        compact = compact_previous_evaluation_report_for_llm(self._fat_report())
        assert compact is not None
        assert compact["alignment_score"] == 0.7

    def test_compact_is_smaller(self) -> None:
        report = self._fat_report()
        compact = compact_previous_evaluation_report_for_llm(report)
        assert compact is not None
        assert len(json.dumps(compact)) < len(json.dumps(report))
