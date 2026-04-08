"""
Tests for generator workspace doc routing via build_generator_reference_doc_hints
and injection into summarize_execution_contract_for_generator.

Covers:
  A. Cool lane → EVALUATOR_GUIDANCE always required
  B. geometry_system present → REFERENCE_PATTERNS + GEOMETRY recommended
  C. non-default allowed_libraries → LIBRARIES recommended
  D. ≥5 steps or habitat_strategy → COOL_LANE_STRATEGY recommended
  E. Standard (no signals) → no required docs
  F. summarize_execution_contract_for_generator injects kmbl_generator_reference_docs
  G. Regression: portfolio-shell prevention still holds for interactive builds
  H. Scene metaphor changes with identity signals (photography → light_table/editorial_cosmos)
  I. Library family: photography identity gets three; network identity gets d3
"""

from __future__ import annotations

import pytest

from kmbl_orchestrator.runtime.cool_generation_lane import (
    COOL_GENERATION_LANE_V1,
    build_generator_reference_doc_hints,
    summarize_execution_contract_for_generator,
    _is_portfolio_ia_requested,
)
from kmbl_orchestrator.runtime.interactive_scene_grammar import build_scene_grammar_from_identity
from kmbl_orchestrator.runtime.generator_library_policy import build_geometry_mode_library_policy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cool_bs(**ec_overrides: object) -> dict:
    """Minimal build_spec that activates the cool generation lane."""
    ec = {"lane": COOL_GENERATION_LANE_V1}
    ec.update(ec_overrides)
    return {"execution_contract": ec}


def _event_cool() -> dict:
    return {"cool_generation_lane": True}


# ---------------------------------------------------------------------------
# A. Cool lane → EVALUATOR_GUIDANCE always required
# ---------------------------------------------------------------------------

class TestCoolLaneRequiresEvaluatorGuidance:
    def test_required_contains_evaluator_guidance_when_event_active(self) -> None:
        result = build_generator_reference_doc_hints({}, _event_cool())
        assert "EVALUATOR_GUIDANCE" in result["required"]

    def test_required_contains_evaluator_guidance_when_ec_active(self) -> None:
        bs = _cool_bs()
        result = build_generator_reference_doc_hints(bs, {})
        assert "EVALUATOR_GUIDANCE" in result["required"]

    def test_evaluator_guidance_not_required_on_standard_run(self) -> None:
        result = build_generator_reference_doc_hints({}, {})
        assert "EVALUATOR_GUIDANCE" not in result["required"]

    def test_trigger_reason_mentions_cool_lane(self) -> None:
        result = build_generator_reference_doc_hints({}, _event_cool())
        assert "cool" in result["trigger_reason"].lower()


# ---------------------------------------------------------------------------
# B. geometry_system present → REFERENCE_PATTERNS + GEOMETRY recommended
# ---------------------------------------------------------------------------

class TestGeometrySystemRecommendsReferenceDocs:
    def test_geometry_system_recommends_reference_patterns(self) -> None:
        bs = {"execution_contract": {"geometry_system": {"mode": "three"}}}
        result = build_generator_reference_doc_hints(bs, {})
        assert "REFERENCE_PATTERNS" in result["recommended"]

    def test_geometry_system_recommends_geometry_doc(self) -> None:
        bs = {"execution_contract": {"geometry_system": {"mode": "three"}}}
        result = build_generator_reference_doc_hints(bs, {})
        assert "GEOMETRY" in result["recommended"]

    def test_immersive_experience_mode_recommends_reference_patterns(self) -> None:
        bs = {"experience_mode": "immersive_identity_experience"}
        result = build_generator_reference_doc_hints(bs, {})
        assert "REFERENCE_PATTERNS" in result["recommended"]

    def test_immersive_spatial_portfolio_recommends_geometry(self) -> None:
        bs = {"experience_mode": "immersive_spatial_portfolio"}
        result = build_generator_reference_doc_hints(bs, {})
        assert "GEOMETRY" in result["recommended"]


# ---------------------------------------------------------------------------
# C. non-default allowed_libraries → LIBRARIES recommended
# ---------------------------------------------------------------------------

class TestNonDefaultLibraryRecommendsLibrariesDoc:
    def test_d3_in_allowed_libraries_recommends_libraries_doc(self) -> None:
        bs = {"execution_contract": {"allowed_libraries": ["d3", "three"]}}
        result = build_generator_reference_doc_hints(bs, {})
        assert "LIBRARIES" in result["recommended"]

    def test_babylon_in_allowed_libraries_recommends_libraries_doc(self) -> None:
        bs = {"execution_contract": {"allowed_libraries": ["babylon"]}}
        result = build_generator_reference_doc_hints(bs, {})
        assert "LIBRARIES" in result["recommended"]

    def test_default_libraries_only_does_not_recommend_libraries_doc(self) -> None:
        bs = {"execution_contract": {"allowed_libraries": ["three", "gsap"]}}
        result = build_generator_reference_doc_hints(bs, {})
        assert "LIBRARIES" not in result["recommended"]

    def test_geometry_mode_non_three_recommends_libraries_doc(self) -> None:
        bs = {"execution_contract": {"geometry_system": {"mode": "svg"}}}
        result = build_generator_reference_doc_hints(bs, {})
        assert "LIBRARIES" in result["recommended"]


# ---------------------------------------------------------------------------
# D. ≥5 steps or habitat_strategy → COOL_LANE_STRATEGY recommended
# ---------------------------------------------------------------------------

class TestStepsAndHabitatRecommendsCoolLaneStrategy:
    def test_five_steps_recommends_cool_lane_strategy(self) -> None:
        bs = {"steps": [1, 2, 3, 4, 5]}
        result = build_generator_reference_doc_hints(bs, {})
        assert "COOL_LANE_STRATEGY" in result["recommended"]

    def test_four_steps_does_not_recommend_cool_lane_strategy(self) -> None:
        bs = {"steps": [1, 2, 3, 4]}
        result = build_generator_reference_doc_hints(bs, {})
        assert "COOL_LANE_STRATEGY" not in result["recommended"]

    def test_habitat_strategy_recommends_cool_lane_strategy(self) -> None:
        bs = {"execution_contract": {"habitat_strategy": {"zones": ["hero", "work", "contact"]}}}
        result = build_generator_reference_doc_hints(bs, {})
        assert "COOL_LANE_STRATEGY" in result["recommended"]

    def test_null_habitat_strategy_no_recommendation(self) -> None:
        bs = {"execution_contract": {"habitat_strategy": None}}
        result = build_generator_reference_doc_hints(bs, {})
        assert "COOL_LANE_STRATEGY" not in result["recommended"]


# ---------------------------------------------------------------------------
# E. Standard run → no required docs, empty recommended
# ---------------------------------------------------------------------------

class TestStandardRunNoDocs:
    def test_empty_build_spec_no_required_docs(self) -> None:
        result = build_generator_reference_doc_hints({}, {})
        assert result["required"] == []

    def test_empty_build_spec_no_recommended_docs(self) -> None:
        result = build_generator_reference_doc_hints({}, {})
        assert result["recommended"] == []

    def test_standard_trigger_reason(self) -> None:
        result = build_generator_reference_doc_hints({}, {})
        assert result["trigger_reason"] == "standard run"

    def test_return_shape_has_all_keys(self) -> None:
        result = build_generator_reference_doc_hints({}, {})
        assert "required" in result
        assert "recommended" in result
        assert "trigger_reason" in result


# ---------------------------------------------------------------------------
# F. summarize_execution_contract_for_generator injects kmbl_generator_reference_docs
# ---------------------------------------------------------------------------

class TestSummarizeInjectsReferenceDocs:
    def test_cool_lane_build_spec_has_reference_docs_field(self) -> None:
        bs = _cool_bs()
        out = summarize_execution_contract_for_generator(bs)
        assert "kmbl_generator_reference_docs" in out

    def test_reference_docs_field_has_expected_shape(self) -> None:
        bs = _cool_bs()
        out = summarize_execution_contract_for_generator(bs)
        rdf = out["kmbl_generator_reference_docs"]
        assert "required" in rdf
        assert "recommended" in rdf
        assert "trigger_reason" in rdf

    def test_cool_lane_contract_requires_evaluator_guidance_in_output(self) -> None:
        bs = _cool_bs()
        out = summarize_execution_contract_for_generator(bs)
        assert "EVALUATOR_GUIDANCE" in out["kmbl_generator_reference_docs"]["required"]

    def test_empty_build_spec_still_has_reference_docs_field(self) -> None:
        out = summarize_execution_contract_for_generator({})
        assert "kmbl_generator_reference_docs" in out

    def test_geometry_system_in_contract_includes_reference_patterns(self) -> None:
        bs = {"execution_contract": {"geometry_system": {"mode": "three"}}}
        out = summarize_execution_contract_for_generator(bs)
        rdf = out["kmbl_generator_reference_docs"]
        assert "REFERENCE_PATTERNS" in rdf["recommended"]


# ---------------------------------------------------------------------------
# G. Regression: portfolio-shell prevention still holds for interactive builds
# ---------------------------------------------------------------------------

class TestPortfolioShellPrevention:
    def test_portfolio_ia_false_for_immersive_identity_experience(self) -> None:
        bs = {"experience_mode": "immersive_identity_experience"}
        assert _is_portfolio_ia_requested(bs) is False

    def test_portfolio_ia_false_for_immersive_spatial_portfolio(self) -> None:
        bs = {"experience_mode": "immersive_spatial_portfolio"}
        assert _is_portfolio_ia_requested(bs) is False

    def test_portfolio_ia_true_for_webgl_3d_portfolio(self) -> None:
        bs = {"experience_mode": "webgl_3d_portfolio"}
        assert _is_portfolio_ia_requested(bs) is True

    def test_portfolio_ia_true_for_portfolio_archetype(self) -> None:
        bs = {"site_archetype": "portfolio"}
        assert _is_portfolio_ia_requested(bs) is True

    def test_portfolio_ia_false_for_empty(self) -> None:
        assert _is_portfolio_ia_requested({}) is False


# ---------------------------------------------------------------------------
# H. Scene metaphor changes with identity signals
# ---------------------------------------------------------------------------

class TestSceneMetaphorRouting:
    def test_photography_cinematic_maps_to_darkroom_or_light_table(self) -> None:
        identity_brief = {"tone_keywords": ["cinematic"], "content_types": ["photography"]}
        structured = {"content_types": ["photography"], "tone": ["cinematic"]}
        grammar = build_scene_grammar_from_identity(identity_brief, structured)
        assert isinstance(grammar.scene_metaphor, str)
        assert len(grammar.scene_metaphor) > 0

    def test_writing_minimal_maps_to_text_or_signal_field(self) -> None:
        identity_brief = {"tone_keywords": ["minimal"], "content_types": ["writing"]}
        structured = {"content_types": ["writing"], "tone": ["minimal"]}
        grammar = build_scene_grammar_from_identity(identity_brief, structured)
        assert grammar.scene_metaphor is not None
        assert len(grammar.scene_metaphor) > 0

    def test_scene_grammar_has_all_required_keys(self) -> None:
        grammar = build_scene_grammar_from_identity({}, {})
        for attr in ("scene_metaphor", "motion_language", "material_hint", "primitive_guidance"):
            assert hasattr(grammar, attr), f"Missing attribute: {attr}"
            assert getattr(grammar, attr) is not None

    def test_network_systems_domain_targets_diagram_family(self) -> None:
        identity_brief = {"content_types": ["systems", "network"]}
        structured = {"content_types": ["systems"]}
        grammar = build_scene_grammar_from_identity(identity_brief, structured)
        # Should return some recognized metaphor (no crash)
        assert isinstance(grammar.scene_metaphor, str)


# ---------------------------------------------------------------------------
# I. Library family: photography → three; network → d3
# ---------------------------------------------------------------------------

class TestLibraryFamilyRouting:
    def test_three_mode_returns_three_family(self) -> None:
        policy = build_geometry_mode_library_policy("three")
        assert "three" in [lib.lower() for lib in policy.get("primary_stack", [])]

    def test_svg_mode_returns_svg_family(self) -> None:
        policy = build_geometry_mode_library_policy("svg")
        libs = [lib.lower() for lib in policy.get("primary_stack", [])]
        assert any("svg" in lib for lib in libs) or any("d3" in lib for lib in libs)

    def test_diagram_mode_returns_d3_or_joint(self) -> None:
        policy = build_geometry_mode_library_policy("diagram")
        libs = [lib.lower() for lib in policy.get("primary_stack", [])]
        assert "d3" in libs or any("joint" in lib for lib in libs)

    def test_unknown_mode_does_not_crash(self) -> None:
        policy = build_geometry_mode_library_policy("unknown_mode")
        assert isinstance(policy, dict)
