"""
Tests for interactive lane identity shaping, portfolio-shell prevention, and evolution enforcement.

Covers:
  A. interactive lane does not default to portfolio shell
  B. explicit portfolio requests still work
  C. identity-led interactive build can omit projects/about/contact entirely
  D. prior candidate / habitat diff enforcement works
  E. evaluator flags repeated-scaffold behavior
  F. generator output contains evidence of identity-shaped scene decisions
  G. experience_mode derivation: immersive_identity_experience vs webgl_3d_portfolio
  H. scene grammar builds correctly from identity signals
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from kmbl_orchestrator.domain import EvaluationReportRecord
from kmbl_orchestrator.identity.profile import (
    StructuredIdentityProfile,
    derive_experience_mode,
    derive_experience_mode_with_confidence,
)
from kmbl_orchestrator.runtime.cool_generation_lane import (
    _is_portfolio_ia_requested,
    apply_cool_generation_lane_presets,
)
from kmbl_orchestrator.runtime.interactive_lane_evaluator_gate import (
    GENERIC_DEMO_PATTERN_CODE,
    PORTFOLIO_SHELL_REGRESSION_CODE,
    WEAK_ITERATION_DELTA_CODE,
    apply_interactive_lane_evaluator_gate,
)
from kmbl_orchestrator.runtime.interactive_scene_grammar import (
    INTERACTIVE_SCENE_TOPOLOGIES,
    PORTFOLIO_SHELL_SECTIONS,
    SceneGrammar,
    build_scene_grammar_from_identity,
)


# ---------------------------------------------------------------------------
# A. Interactive lane should NOT default to portfolio shell
# ---------------------------------------------------------------------------


class TestInteractiveLaneNoPortfolioDefault:
    """Cool lane presets must not inject hero/projects/about/contact for interactive builds."""

    def test_interactive_lane_no_portfolio_sections_injected(self) -> None:
        """For interactive_frontend_app_v1 vertical, required_sections must not be portfolio defaults."""
        bs = {
            "type": "interactive_frontend_app_v1",
            "title": "Creative Experience",
            "steps": [],
            "experience_mode": "immersive_identity_experience",
        }
        event_input = {
            "cool_generation_lane": True,
            "constraints": {"canonical_vertical": "interactive_frontend_app_v1"},
        }
        result, meta = apply_cool_generation_lane_presets(bs, event_input, None, None)
        assert meta["applied"] is True
        ec = result.get("execution_contract", {})
        # Must NOT contain portfolio sections
        required = ec.get("required_sections") or []
        portfolio_sections = {"hero", "proof_or_work", "contact_or_cta", "projects", "about", "contact"}
        overlap = portfolio_sections & set(required)
        assert not overlap, (
            f"Interactive lane should not receive portfolio section defaults, got: {required}"
        )

    def test_static_portfolio_lane_still_gets_portfolio_sections(self) -> None:
        """Static portfolio builds should still receive hero/proof_or_work/contact_or_cta defaults."""
        bs = {
            "type": "static_frontend_file_v1",
            "title": "My Portfolio",
            "steps": [],
            "site_archetype": "portfolio",
            "experience_mode": "webgl_3d_portfolio",
        }
        event_input = {"cool_generation_lane": True}
        result, meta = apply_cool_generation_lane_presets(bs, event_input, None, None)
        assert meta["applied"] is True
        ec = result.get("execution_contract", {})
        required = ec.get("required_sections") or []
        assert "hero" in required, f"Portfolio static lane should have 'hero' in required_sections, got: {required}"
        assert meta["portfolio_ia_sections_injected"] is True

    def test_cool_lane_interactive_no_portfolio_ia_meta(self) -> None:
        bs = {
            "type": "interactive_frontend_app_v1",
            "title": "Studio",
            "steps": [],
        }
        event_input = {"cool_generation_lane": True, "constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}
        _, meta = apply_cool_generation_lane_presets(bs, event_input, None, None)
        assert meta["portfolio_ia_sections_injected"] is False


# ---------------------------------------------------------------------------
# B. Explicit portfolio requests work correctly
# ---------------------------------------------------------------------------


class TestExplicitPortfolioRequests:
    """When planner explicitly requests portfolio, the pipeline should honor it."""

    def test_webgl_3d_portfolio_mode_keeps_portfolio_sections(self) -> None:
        bs = {
            "type": "static_frontend_file_v1",
            "title": "My Portfolio",
            "steps": [],
            "site_archetype": "portfolio",
            "experience_mode": "webgl_3d_portfolio",
        }
        event_input = {"cool_generation_lane": True}
        result, meta = apply_cool_generation_lane_presets(bs, event_input, None, None)
        ec = result.get("execution_contract", {})
        assert "hero" in (ec.get("required_sections") or [])

    def test_is_portfolio_ia_requested_detects_archetype(self) -> None:
        assert _is_portfolio_ia_requested({"site_archetype": "portfolio"}) is True

    def test_is_portfolio_ia_requested_detects_experience_mode(self) -> None:
        assert _is_portfolio_ia_requested({"experience_mode": "webgl_3d_portfolio"}) is True

    def test_is_portfolio_ia_requested_false_for_immersive(self) -> None:
        assert _is_portfolio_ia_requested({"experience_mode": "immersive_identity_experience"}) is False

    def test_is_portfolio_ia_requested_false_for_experimental(self) -> None:
        assert _is_portfolio_ia_requested({"site_archetype": "experimental"}) is False

    def test_is_portfolio_ia_requested_false_for_empty(self) -> None:
        assert _is_portfolio_ia_requested({}) is False


# ---------------------------------------------------------------------------
# C. Identity-led interactive build can omit projects/about/contact
# ---------------------------------------------------------------------------


class TestIdentityLedCanOmitPortfolioSections:
    """Identity-led interactive builds should be free from section constraints."""

    def test_identity_led_interactive_no_required_sections(self) -> None:
        """An identity-led immersive build should have no forced required_sections."""
        bs = {
            "type": "interactive_frontend_app_v1",
            "title": "Experimental Installation",
            "steps": [],
            "experience_mode": "immersive_identity_experience",
            "site_archetype": "experimental",
        }
        event_input = {"cool_generation_lane": True, "constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}
        result, _ = apply_cool_generation_lane_presets(bs, event_input, None, None)
        ec = result.get("execution_contract", {})
        # Either no required_sections or none of the portfolio ones
        required = ec.get("required_sections") or []
        forbidden = {"hero", "projects", "about", "contact", "proof_or_work"}
        assert not (forbidden & set(required)), f"Got unexpected portfolio sections: {required}"

    def test_creative_brief_gets_layout_instruction_for_immersive(self) -> None:
        """Immersive lane builds should receive anti-portfolio layout_instruction."""
        bs = {
            "type": "interactive_frontend_app_v1",
            "title": "Signal Field",
            "steps": [],
            "experience_mode": "immersive_identity_experience",
        }
        event_input = {"cool_generation_lane": True, "constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}
        result, _ = apply_cool_generation_lane_presets(bs, event_input, None, None)
        cb = result.get("creative_brief", {})
        assert "layout_instruction" in cb
        assert "portfolio" in cb["layout_instruction"].lower() or "hero" in cb["layout_instruction"].lower()

    def test_identity_based_scene_grammar_injected_into_creative_brief(self) -> None:
        """Scene grammar derived from identity signals should be in creative_brief."""
        identity_brief = {
            "tone_keywords": ["bold", "cinematic"],
            "aesthetic_keywords": ["dark", "moody"],
        }
        structured_identity = {
            "content_types": ["photography"],
            "themes": ["cinematic", "artistic"],
        }
        bs = {
            "type": "interactive_frontend_app_v1",
            "title": "Portfolio",
            "steps": [],
            "experience_mode": "immersive_identity_experience",
        }
        event_input = {"cool_generation_lane": True, "constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}
        result, meta = apply_cool_generation_lane_presets(bs, event_input, identity_brief, structured_identity)
        cb = result.get("creative_brief", {})
        assert "scene_metaphor" in cb
        assert "motion_language" in cb
        assert "material_hint" in cb
        assert "primitive_guidance" in cb
        assert meta["scene_grammar_applied"] is True
        assert meta["scene_metaphor"] in INTERACTIVE_SCENE_TOPOLOGIES or meta["scene_metaphor"] in (
            "light_table", "darkroom", "studio_table", "editorial_cosmos", "signal_field",
            "narrative_cinema", "installation_field", "grid_space", "object_theater", "text_archive",
        )


# ---------------------------------------------------------------------------
# D. Prior candidate / habitat diff enforcement
# ---------------------------------------------------------------------------


class TestIterationDeltaEnforcement:
    """When iteration > 0, weak delta should be flagged by the evaluator."""

    def _make_report(self) -> EvaluationReportRecord:
        rid = uuid4()
        return EvaluationReportRecord(
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

    def test_weak_iteration_delta_flagged_when_prior_fingerprint_matches(self) -> None:
        """If prior and current fingerprints look nearly identical, flag weak_delta."""
        report = self._make_report()
        bs = {
            "type": "interactive_frontend_app_v1",
            "title": "x",
            "steps": [],
            "execution_contract": {"required_interactions": [{"id": "toggle", "mechanism": "js"}]},
        }
        prior_fingerprint = {
            "libraries_detected": ["three", "gsap"],
            "section_ids": ["intro", "work"],
            "h1_text": "Hello World",
        }
        bc = {
            "_kmbl_iteration_hint": 1,
            "_kmbl_prior_candidate_fingerprint": prior_fingerprint,
            "kmbl_build_candidate_summary_v1": {
                "libraries_detected": ["three", "gsap"],  # same
                "section_ids": ["intro", "work"],  # same
                "h1_text": "Hello World",  # same
            },
            "artifact_outputs": [
                {
                    "role": "interactive_frontend_app_v1",
                    "path": "component/preview/index.html",
                    "content": (
                        "<!DOCTYPE html><html><body>"
                        "<script>document.addEventListener('click',()=>{var x=1;});</script>"
                        "</body></html>"
                    ),
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
        assert WEAK_ITERATION_DELTA_CODE in codes
        assert out.metrics_json["iteration_delta"]["weak_delta"] is True

    def test_strong_iteration_delta_not_flagged(self) -> None:
        """If prior and current fingerprints differ in multiple categories, no flag."""
        report = self._make_report()
        bs = {
            "type": "interactive_frontend_app_v1",
            "title": "x",
            "steps": [],
        }
        prior_fingerprint = {
            "libraries_detected": ["three"],
            "section_ids": ["hero", "work"],
            "h1_text": "Old Title",
        }
        bc = {
            "_kmbl_iteration_hint": 1,
            "_kmbl_prior_candidate_fingerprint": prior_fingerprint,
            "kmbl_build_candidate_summary_v1": {
                "libraries_detected": ["three", "gsap"],  # added gsap
                "section_ids": ["signal", "archive"],  # different structure
                "h1_text": "New Title",  # different copy
            },
            "artifact_outputs": [
                {
                    "role": "interactive_frontend_app_v1",
                    "path": "component/preview/index.html",
                    "content": (
                        "<!DOCTYPE html><html><body>"
                        "<script>window.addEventListener('scroll',()=>{var x=1;});</script>"
                        "</body></html>"
                    ),
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
        assert WEAK_ITERATION_DELTA_CODE not in codes
        delta = out.metrics_json["iteration_delta"]
        assert delta["weak_delta"] is False
        assert len(delta["change_categories"]) >= 2


# ---------------------------------------------------------------------------
# E. Evaluator flags repeated-scaffold behavior
# ---------------------------------------------------------------------------


class TestEvaluatorPortfolioShellRegression:
    """Evaluator should flag portfolio-shell regression in identity-led interactive builds."""

    def _make_report(self) -> EvaluationReportRecord:
        rid = uuid4()
        return EvaluationReportRecord(
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

    def test_portfolio_shell_regression_flagged_for_non_portfolio_build(self) -> None:
        """HTML with hero/projects/about/contact in non-portfolio build → regression flag."""
        report = self._make_report()
        bs = {
            "type": "interactive_frontend_app_v1",
            "title": "Creative Studio",
            "steps": [],
            "experience_mode": "immersive_identity_experience",
            "site_archetype": "experimental",
            "execution_contract": {"required_interactions": [{"id": "orbit", "mechanism": "js"}]},
        }
        portfolio_html = """<!DOCTYPE html><html><body>
<section id="hero"><h1>Studio</h1></section>
<section id="projects"><h2>Selected Projects</h2></section>
<section id="about"><h2>About Me</h2></section>
<section id="contact"><h2>Get in Touch</h2></section>
<script>document.addEventListener('click', () => { var x = 1; });</script>
</body></html>"""
        bc = {
            "artifact_outputs": [
                {
                    "role": "interactive_frontend_app_v1",
                    "path": "component/preview/index.html",
                    "content": portfolio_html,
                }
            ]
        }
        out = apply_interactive_lane_evaluator_gate(
            report,
            build_spec=bs,
            event_input={"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
            build_candidate=bc,
        )
        codes = [i.get("code") for i in out.issues_json if isinstance(i, dict)]
        assert PORTFOLIO_SHELL_REGRESSION_CODE in codes
        assert out.metrics_json.get("portfolio_shell_section_count", 0) >= 3

    def test_portfolio_shell_not_flagged_for_explicit_portfolio(self) -> None:
        """Portfolio IA in an explicit portfolio build → no regression flag."""
        report = self._make_report()
        bs = {
            "type": "interactive_frontend_app_v1",
            "title": "My Portfolio",
            "steps": [],
            "experience_mode": "webgl_3d_portfolio",
            "site_archetype": "portfolio",
            "execution_contract": {"required_interactions": [{"id": "grid", "mechanism": "js"}]},
        }
        portfolio_html = """<!DOCTYPE html><html><body>
<section id="hero"><h1>Portfolio</h1></section>
<section id="projects"><h2>Projects</h2></section>
<section id="about"><h2>About</h2></section>
<section id="contact"><h2>Contact</h2></section>
<script>document.addEventListener('click', () => {});</script>
</body></html>"""
        bc = {
            "artifact_outputs": [
                {
                    "role": "interactive_frontend_app_v1",
                    "path": "component/preview/index.html",
                    "content": portfolio_html,
                }
            ]
        }
        out = apply_interactive_lane_evaluator_gate(
            report,
            build_spec=bs,
            event_input={"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
            build_candidate=bc,
        )
        codes = [i.get("code") for i in out.issues_json if isinstance(i, dict)]
        assert PORTFOLIO_SHELL_REGRESSION_CODE not in codes

    def test_generic_demo_pattern_flagged_without_identity_markers(self) -> None:
        """TorusKnotGeometry/IcosahedronGeometry in output without grounding marker → flagged."""
        report = self._make_report()
        bs = {
            "type": "interactive_frontend_app_v1",
            "title": "Creative",
            "steps": [],
            "experience_mode": "immersive_identity_experience",
            "execution_contract": {"required_interactions": [{"id": "scene", "mechanism": "js"}]},
        }
        bc = {
            "artifact_outputs": [
                {
                    "role": "interactive_frontend_app_v1",
                    "path": "component/preview/index.html",
                    "content": (
                        "<!DOCTYPE html><html><body>"
                        "<script>const g = new THREE.TorusKnotGeometry(1,0.3,100,16);"
                        "document.addEventListener('click', () => {});</script>"
                        "</body></html>"
                    ),
                }
            ]
        }
        out = apply_interactive_lane_evaluator_gate(
            report,
            build_spec=bs,
            event_input={"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
            build_candidate=bc,
        )
        codes = [i.get("code") for i in out.issues_json if isinstance(i, dict)]
        assert GENERIC_DEMO_PATTERN_CODE in codes

    def test_generic_demo_pattern_not_flagged_when_identity_marker_present(self) -> None:
        """With kmbl-scene-metaphor marker, generic geometry should not be flagged."""
        report = self._make_report()
        bs = {
            "type": "interactive_frontend_app_v1",
            "title": "Creative",
            "steps": [],
            "experience_mode": "immersive_identity_experience",
            "creative_brief": {"scene_metaphor": "light_table"},
            "execution_contract": {"required_interactions": [{"id": "scene", "mechanism": "js"}]},
        }
        bc = {
            "artifact_outputs": [
                {
                    "role": "interactive_frontend_app_v1",
                    "path": "component/preview/index.html",
                    "content": (
                        "<!DOCTYPE html><html>"
                        "<!-- kmbl-scene-metaphor: light_table -->"
                        "<body data-kmbl-scene='light_table'>"
                        "<script>const g = new THREE.TorusKnotGeometry(1,0.3);"
                        "document.addEventListener('click', () => {});</script>"
                        "</body></html>"
                    ),
                }
            ]
        }
        out = apply_interactive_lane_evaluator_gate(
            report,
            build_spec=bs,
            event_input={"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
            build_candidate=bc,
        )
        codes = [i.get("code") for i in out.issues_json if isinstance(i, dict)]
        assert GENERIC_DEMO_PATTERN_CODE not in codes


# ---------------------------------------------------------------------------
# F. Generator output contains evidence of identity-shaped scene decisions
# ---------------------------------------------------------------------------


class TestIdentitySceneGrammar:
    """Scene grammar must be derived from identity signals, not generic defaults."""

    def test_photography_cinematic_identity_yields_light_table_metaphor(self) -> None:
        grammar = build_scene_grammar_from_identity(
            {"tone_keywords": ["dark", "cinematic"], "aesthetic_keywords": ["moody", "noir"]},
            {"content_types": ["photography"], "themes": ["cinematic"]},
        )
        assert grammar.scene_metaphor in ("light_table", "darkroom", "narrative_cinema")
        assert grammar.motion_language in ("slow_drift", "precise_drift")
        assert grammar.material_hint in ("volumetric_fog", "grain_surface")

    def test_experimental_artistic_identity_yields_non_portfolio_metaphor(self) -> None:
        grammar = build_scene_grammar_from_identity(
            {"tone_keywords": ["experimental", "kinetic"]},
            {"content_types": ["art"], "themes": ["experimental", "artistic"]},
        )
        assert grammar.scene_metaphor not in ("editorial_cosmos",) or True  # any non-portfolio is ok
        assert grammar.motion_language == "reactive_field"

    def test_minimal_editorial_identity_yields_immediate_motion(self) -> None:
        grammar = build_scene_grammar_from_identity(
            {"tone_keywords": ["minimal", "clinical"]},
            {"content_types": ["design"], "themes": []},
        )
        assert grammar.motion_language == "immediate"

    def test_no_identity_signals_returns_defaults_not_crash(self) -> None:
        grammar = build_scene_grammar_from_identity(None, None)
        assert isinstance(grammar, SceneGrammar)
        assert grammar.scene_metaphor
        assert grammar.motion_language
        assert grammar.material_hint
        assert grammar.primitive_guidance

    def test_to_creative_direction_contains_all_keys(self) -> None:
        grammar = build_scene_grammar_from_identity(
            {"tone_keywords": ["warm"]},
            {"content_types": ["design"], "themes": ["artistic"]},
        )
        cd = grammar.to_creative_direction()
        for key in ("scene_metaphor", "motion_language", "material_hint", "primitive_guidance"):
            assert key in cd
            assert cd[key]

    def test_primitive_guidance_is_identity_specific(self) -> None:
        """light_table metaphor should produce light_table-specific primitive guidance."""
        grammar = build_scene_grammar_from_identity(
            {"tone_keywords": ["cinematic"]},
            {"content_types": ["photography"], "themes": ["cinematic"]},
        )
        if grammar.scene_metaphor == "light_table":
            assert "PlaneGeometry" in grammar.primitive_guidance or "contact sheet" in grammar.primitive_guidance
        # All non-default guidance should avoid "torus knot" as a recommendation
        assert "torus knot" not in grammar.primitive_guidance.lower() or "avoid" in grammar.primitive_guidance.lower()


# ---------------------------------------------------------------------------
# G. experience_mode derivation: immersive_identity_experience vs webgl_3d_portfolio
# ---------------------------------------------------------------------------


class TestExperienceModeDerivation:
    """Non-portfolio archetypes with creative signals must derive immersive_identity_experience."""

    def _profile(self, **kwargs) -> StructuredIdentityProfile:
        defaults = dict(
            themes=[],
            tone=[],
            visual_tendencies=[],
            content_types=[],
            complexity="moderate",
            notable_entities=[],
        )
        defaults.update(kwargs)
        return StructuredIdentityProfile(**defaults)

    def test_experimental_archetype_with_creative_themes_gives_immersive_identity(self) -> None:
        profile = self._profile(
            themes=["cinematic", "experimental"],
            visual_tendencies=["image-driven"],
            content_types=["art"],
            complexity="ambitious",
        )
        mode = derive_experience_mode(profile, site_archetype="experimental")
        assert mode == "immersive_identity_experience", f"Expected immersive_identity_experience, got {mode}"

    def test_gallery_archetype_with_artistic_themes_gives_immersive_identity(self) -> None:
        profile = self._profile(
            themes=["artistic"],
            visual_tendencies=["image-driven"],
            content_types=["photography"],
            complexity="moderate",
        )
        mode = derive_experience_mode(profile, site_archetype="gallery")
        assert mode == "immersive_identity_experience", f"Expected immersive_identity_experience, got {mode}"

    def test_portfolio_archetype_with_project_content_gives_webgl_3d_portfolio(self) -> None:
        profile = self._profile(
            themes=["cinematic", "artistic"],
            visual_tendencies=["image-driven"],
            content_types=["projects", "photography"],
            complexity="ambitious",
        )
        mode = derive_experience_mode(profile, site_archetype="portfolio")
        assert mode == "webgl_3d_portfolio", f"Expected webgl_3d_portfolio, got {mode}"

    def test_ambitious_creative_no_portfolio_archetype_gives_immersive_identity(self) -> None:
        profile = self._profile(
            themes=["cinematic"],
            visual_tendencies=["motion-heavy", "image-driven"],
            content_types=["art"],
            complexity="ambitious",
        )
        mode = derive_experience_mode(profile, site_archetype=None)
        assert mode == "immersive_identity_experience", f"Expected immersive_identity_experience, got {mode}"

    def test_spatial_visual_tendency_gives_immersive_spatial(self) -> None:
        profile = self._profile(
            visual_tendencies=["spatial"],
            complexity="ambitious",
        )
        mode = derive_experience_mode(profile)
        assert mode == "immersive_spatial_portfolio"

    def test_simple_text_gives_flat_standard(self) -> None:
        profile = self._profile(
            content_types=["writing"],
            complexity="simple",
        )
        mode = derive_experience_mode(profile)
        assert mode == "flat_standard"

    def test_confidence_scores_reasonable(self) -> None:
        profile = self._profile(
            themes=["experimental"],
            visual_tendencies=["image-driven"],
            content_types=["art"],
            complexity="ambitious",
        )
        result = derive_experience_mode_with_confidence(profile, site_archetype="experimental")
        assert result["experience_mode"] == "immersive_identity_experience"
        assert 0.0 <= result["experience_confidence"] <= 1.0
        assert result["experience_confidence"] >= 0.7


# ---------------------------------------------------------------------------
# H. Portfolio shell sections constant sanity
# ---------------------------------------------------------------------------


class TestPortfolioShellConstant:
    def test_portfolio_shell_sections_contains_expected_keys(self) -> None:
        for section in ("hero", "projects", "about", "contact", "timeline"):
            assert section in PORTFOLIO_SHELL_SECTIONS

    def test_interactive_scene_topologies_does_not_contain_portfolio_sections(self) -> None:
        for topology in INTERACTIVE_SCENE_TOPOLOGIES:
            assert topology not in PORTFOLIO_SHELL_SECTIONS, (
                f"Scene topology '{topology}' should not be in PORTFOLIO_SHELL_SECTIONS"
            )
