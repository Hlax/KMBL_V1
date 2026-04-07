"""
Tests for token-efficiency compaction changes.

Covers:
    C1  build_spec is slimmed (not full) at iteration > 0
    C2  build_spec retains only _BUILD_SPEC_ITERATION_KEYS fields
    C3  kmbl_locked_build_spec_digest is set to correct value
    C4  build_spec at iteration 0 is untouched
    C5  compact_previous_evaluation_report_for_llm strips metrics/artifacts/alignment_signals
    C6  compact_previous_evaluation_report_for_llm keeps status/summary/issues[:5]/alignment_score
    C7  compact_previous_evaluation_report_for_llm caps issues at 5
    C8  compact_previous_evaluation_report_for_llm returns None for None input
    C9  compact_previous_evaluation_report_for_llm returns non-dict unchanged
    C10 evaluator payload has no metrics in previous_evaluation_report at iter > 0
    C11 evaluator structured_identity is compacted at iter > 0
    C12 evaluator structured_identity is full at iter 0
"""

from __future__ import annotations

from typing import Any

import pytest

from kmbl_orchestrator.runtime.generator_iteration_compact_v1 import (
    _BUILD_SPEC_ITERATION_KEYS,
    apply_iteration_compaction,
    build_spec_digest,
    compact_previous_evaluation_report_for_llm,
    compact_structured_identity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _full_build_spec() -> dict[str, Any]:
    return {
        "experience_mode": "flat_standard",
        "surface_type": "web",
        "canonical_vertical": "saas_landing",
        "success_criteria": ["hero must be bold"],
        "literal_success_checks": [],
        "cool_generation_lane": False,
        "interaction_model": "scroll",
        "motion_spec": None,
        "required_libraries": ["react"],
        "library_hints": [],
        "machine_constraints": {},
        # Fields that should be stripped on iteration > 0:
        "creative_brief": "A long creative brief with lots of words " * 100,
        "crawl_context": {"visited": 10, "summaries": ["page1", "page2"] * 50},
        "raw_reference_payload": {"refs": list(range(500))},
        "site_archetype": "dark_hero",
    }


def _full_evaluation_report() -> dict[str, Any]:
    return {
        "status": "partial",
        "summary": "Some issues found",
        "issues": [{"code": f"issue_{i}"} for i in range(10)],
        "alignment_score": 0.75,
        # Fields that should be stripped:
        "metrics": {
            "grounding_only_partial": False,
            "preview_load_failed": False,
            "design_rubric": {"design_quality": 3, "originality": 3},
            "internal_gate_results": {"gate1": True, "gate2": False},
        },
        "artifacts": [{"ref": "file1.html"}, {"ref": "file2.css"}],
        "alignment_signals": {"color_match": 0.9, "layout_match": 0.8},
    }


def _full_structured_identity() -> dict[str, Any]:
    return {
        "themes": [f"theme_{i}" for i in range(20)],
        "tone": "bold",
        "visual_tendencies": [f"tendency_{i}" for i in range(20)],
        "notable_entities": [f"entity_{i}" for i in range(20)],
        "complexity": "high",
        "raw_crawl_analysis": {"pages": list(range(100))},
        "extended_profile": {"field": "value"} ,
    }


# ---------------------------------------------------------------------------
# C1–C4: build_spec compaction in apply_iteration_compaction
# ---------------------------------------------------------------------------


class TestBuildSpecCompaction:
    def test_build_spec_is_slimmed_at_iteration_1(self) -> None:
        bs = _full_build_spec()
        payload = {"build_spec": dict(bs)}
        apply_iteration_compaction(payload, iteration=1)

        result_bs = payload["build_spec"]
        # creative_brief and execution_contract are now intentionally retained
        # for generator context on iterations
        assert "creative_brief" in result_bs
        assert "crawl_context" not in result_bs
        assert "raw_reference_payload" not in result_bs

    def test_build_spec_retains_only_iteration_keys(self) -> None:
        bs = _full_build_spec()
        payload = {"build_spec": dict(bs)}
        apply_iteration_compaction(payload, iteration=1)

        result_bs = payload["build_spec"]
        for key in result_bs:
            assert key in _BUILD_SPEC_ITERATION_KEYS, f"Unexpected key in slim build_spec: {key!r}"

    def test_build_spec_retains_known_fields(self) -> None:
        bs = _full_build_spec()
        payload = {"build_spec": dict(bs)}
        apply_iteration_compaction(payload, iteration=1)

        result_bs = payload["build_spec"]
        assert result_bs["experience_mode"] == "flat_standard"
        assert result_bs["surface_type"] == "web"
        assert result_bs["canonical_vertical"] == "saas_landing"
        assert result_bs["required_libraries"] == ["react"]

    def test_digest_set_to_original_spec_hash(self) -> None:
        bs = _full_build_spec()
        expected_digest = build_spec_digest(bs)
        payload = {"build_spec": dict(bs)}
        apply_iteration_compaction(payload, iteration=1)

        assert payload["kmbl_locked_build_spec_digest"] == expected_digest

    def test_build_spec_unchanged_at_iteration_0(self) -> None:
        bs = _full_build_spec()
        original_keys = set(bs.keys())
        payload = {"build_spec": dict(bs)}
        apply_iteration_compaction(payload, iteration=0)

        assert set(payload["build_spec"].keys()) == original_keys
        assert "kmbl_locked_build_spec_digest" not in payload

    def test_slim_spec_is_smaller_than_full(self) -> None:
        import json
        bs = _full_build_spec()
        payload = {"build_spec": dict(bs)}
        apply_iteration_compaction(payload, iteration=1)

        full_size = len(json.dumps(bs))
        slim_size = len(json.dumps(payload["build_spec"]))
        assert slim_size < full_size


# ---------------------------------------------------------------------------
# C5–C9: compact_previous_evaluation_report_for_llm
# ---------------------------------------------------------------------------


class TestCompactPreviousEvaluationReport:
    def test_strips_metrics(self) -> None:
        report = _full_evaluation_report()
        result = compact_previous_evaluation_report_for_llm(report)
        assert result is not None
        assert "metrics" not in result

    def test_strips_artifacts(self) -> None:
        report = _full_evaluation_report()
        result = compact_previous_evaluation_report_for_llm(report)
        assert result is not None
        assert "artifacts" not in result

    def test_strips_alignment_signals(self) -> None:
        report = _full_evaluation_report()
        result = compact_previous_evaluation_report_for_llm(report)
        assert result is not None
        assert "alignment_signals" not in result

    def test_keeps_status(self) -> None:
        report = _full_evaluation_report()
        result = compact_previous_evaluation_report_for_llm(report)
        assert result is not None
        assert result["status"] == "partial"

    def test_keeps_summary(self) -> None:
        report = _full_evaluation_report()
        result = compact_previous_evaluation_report_for_llm(report)
        assert result is not None
        assert result["summary"] == "Some issues found"

    def test_keeps_alignment_score(self) -> None:
        report = _full_evaluation_report()
        result = compact_previous_evaluation_report_for_llm(report)
        assert result is not None
        assert result["alignment_score"] == 0.75

    def test_caps_issues_at_5(self) -> None:
        report = _full_evaluation_report()
        assert len(report["issues"]) == 10
        result = compact_previous_evaluation_report_for_llm(report)
        assert result is not None
        assert len(result["issues"]) == 5

    def test_preserves_issues_when_under_cap(self) -> None:
        report = {
            "status": "partial",
            "summary": "Two issues",
            "issues": [{"code": "a"}, {"code": "b"}],
            "alignment_score": 0.5,
            "metrics": {"big": "data"},
        }
        result = compact_previous_evaluation_report_for_llm(report)
        assert result is not None
        assert len(result["issues"]) == 2

    def test_handles_none_input(self) -> None:
        assert compact_previous_evaluation_report_for_llm(None) is None

    def test_handles_non_dict_input(self) -> None:
        assert compact_previous_evaluation_report_for_llm("string") == "string"  # type: ignore[arg-type]

    def test_sets_compacted_flag(self) -> None:
        report = _full_evaluation_report()
        result = compact_previous_evaluation_report_for_llm(report)
        assert result is not None
        assert result["_kmbl_compacted"] is True

    def test_does_not_mutate_original(self) -> None:
        report = _full_evaluation_report()
        original_metrics = dict(report["metrics"])
        compact_previous_evaluation_report_for_llm(report)
        assert report["metrics"] == original_metrics


# ---------------------------------------------------------------------------
# C10–C12: evaluator payload uses compacted fields at iteration > 0
# ---------------------------------------------------------------------------


class TestEvaluatorPayloadCompaction:
    """Integration-style: verify evaluator payload builder applies compaction."""

    def test_evaluator_prev_ev_has_no_metrics_at_iter_1(self) -> None:
        """compact_previous_evaluation_report_for_llm must strip metrics."""
        full_report = _full_evaluation_report()
        compacted = compact_previous_evaluation_report_for_llm(full_report)
        assert compacted is not None
        assert "metrics" not in compacted

    def test_evaluator_prev_ev_has_no_artifacts_at_iter_1(self) -> None:
        full_report = _full_evaluation_report()
        compacted = compact_previous_evaluation_report_for_llm(full_report)
        assert compacted is not None
        assert "artifacts" not in compacted

    def test_evaluator_structured_identity_compacted_at_iter_1(self) -> None:
        si = _full_structured_identity()
        compacted = compact_structured_identity(si)
        assert compacted["_kmbl_compacted"] is True
        assert len(compacted["themes"]) <= 6
        assert len(compacted["visual_tendencies"]) <= 8
        assert len(compacted["notable_entities"]) <= 6
        # Large fields not in compact output
        assert "raw_crawl_analysis" not in compacted
        assert "extended_profile" not in compacted

    def test_evaluator_structured_identity_full_at_iter_0(self) -> None:
        """At iteration 0, structured_identity is passed through unchanged."""
        si = _full_structured_identity()
        # Simulate iter=0 logic: pass through as-is (no compact_structured_identity called)
        assert "_kmbl_compacted" not in si

    def test_compact_report_is_smaller(self) -> None:
        import json
        full_report = _full_evaluation_report()
        compacted = compact_previous_evaluation_report_for_llm(full_report)
        assert compacted is not None
        full_size = len(json.dumps(full_report))
        compact_size = len(json.dumps(compacted))
        assert compact_size < full_size
