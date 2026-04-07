"""
Comprehensive tests for Geometry Brain upgrade.

Covers:
  A. Geometry Contract V1 derivation
  B. Scene Manifest V1 parsing and fingerprint computation
  C. Scene fingerprint persistence in build_candidate_summary_v1
  D. Evolution delta gate using scene_evolution_delta from summary (no silent skip)
  E. Geometry-mode-driven library policy
  F. Non-portfolio immersive runs use geometry contract without portfolio sections
  G. Compact prompt strategy: geometry_system in execution_contract, not only prose
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from kmbl_orchestrator.contracts.geometry_contract_v1 import (
    GEOMETRY_MODE_LIBRARY_MAP,
    GEOMETRY_MODES,
    GeometryContractV1,
    derive_geometry_contract,
    geometry_mode_to_library_recommendations,
)
from kmbl_orchestrator.contracts.scene_manifest_v1 import (
    EVOLUTION_CATEGORIES,
    SceneManifestV1,
    build_fingerprint_from_manifest,
    build_fingerprint_from_summary_fields,
    build_scene_fingerprint_v1,
    compute_scene_evolution_delta,
    manifest_to_fingerprint_data,
    parse_scene_manifest_from_raw,
)
from kmbl_orchestrator.domain import EvaluationReportRecord
from kmbl_orchestrator.runtime.build_candidate_summary_v1 import (
    build_build_candidate_summary_v1,
)
from kmbl_orchestrator.runtime.cool_generation_lane import apply_cool_generation_lane_presets
from kmbl_orchestrator.runtime.generator_iteration_compact_v1 import (
    compact_scene_fingerprint_for_prior,
)
from kmbl_orchestrator.runtime.generator_library_policy import (
    GENERATOR_ANTI_PATTERNS,
    GEOMETRY_LANE_LIBRARIES,
    build_geometry_mode_library_policy,
)
from kmbl_orchestrator.runtime.interactive_lane_evaluator_gate import (
    WEAK_ITERATION_DELTA_CODE,
    apply_interactive_lane_evaluator_gate,
)


# ---------------------------------------------------------------------------
# A. Geometry Contract V1 derivation
# ---------------------------------------------------------------------------


class TestGeometryContractDerivation:
    """derive_geometry_contract() maps identity signals to typed geometry rules."""

    def test_photography_cinematic_identity_yields_three_mode(self) -> None:
        contract = derive_geometry_contract(
            {"tone_keywords": ["cinematic", "dark"], "aesthetic_keywords": ["noir"]},
            {"content_types": ["photography"], "themes": ["cinematic"], "complexity": "ambitious"},
            {"experience_mode": "immersive_identity_experience"},
        )
        assert contract.mode == "three"

    def test_network_systems_identity_yields_diagram_mode(self) -> None:
        contract = derive_geometry_contract(
            {"tone_keywords": ["precise"], "aesthetic_keywords": ["technical"]},
            {"content_types": ["data", "network"], "themes": ["network", "systems"], "complexity": "ambitious"},
            {},
        )
        assert contract.mode == "diagram"

    def test_writing_only_simple_yields_css_spatial_or_svg(self) -> None:
        contract = derive_geometry_contract(
            {"tone_keywords": ["minimal"], "aesthetic_keywords": ["editorial"]},
            {"content_types": ["writing"], "themes": [], "complexity": "simple"},
            {},
        )
        assert contract.mode in ("css_spatial", "svg", "hybrid_three_svg")

    def test_experimental_artistic_no_network_yields_three(self) -> None:
        contract = derive_geometry_contract(
            {"tone_keywords": ["experimental", "kinetic"]},
            {"content_types": ["art"], "themes": ["experimental"], "complexity": "ambitious"},
            {},
        )
        assert contract.mode == "three"

    def test_composition_rules_include_anti_portfolio(self) -> None:
        contract = derive_geometry_contract(
            {},
            {"content_types": ["photography"], "themes": ["cinematic"], "complexity": "moderate"},
            {"experience_mode": "immersive_identity_experience"},
        )
        portfolio_rule = next(
            (r for r in contract.composition_rules if "portfolio" in r.lower() or "hero" in r.lower() or "section" in r.lower()),
            None,
        )
        assert portfolio_rule is not None, f"Expected anti-portfolio rule in: {contract.composition_rules}"

    def test_motion_rules_derived_from_tone(self) -> None:
        contract = derive_geometry_contract(
            {"tone_keywords": ["restrained"]},
            {"themes": [], "complexity": "moderate"},
            {},
        )
        assert contract.motion_mapping_rules
        assert any("drift" in r.lower() or "bounce" in r.lower() for r in contract.motion_mapping_rules)

    def test_minimal_tone_yields_immediate_motion(self) -> None:
        contract = derive_geometry_contract(
            {"tone_keywords": ["minimal", "clinical"]},
            {"themes": [], "complexity": "simple"},
            {},
        )
        assert any("immediate" in r.lower() or "no decorative" in r.lower() for r in contract.motion_mapping_rules)

    def test_photography_topology_yields_identity_primitives(self) -> None:
        contract = derive_geometry_contract(
            {},
            {"content_types": ["photography"], "themes": ["cinematic"], "complexity": "ambitious"},
            {"creative_brief": {"scene_metaphor": "light_table"}},
        )
        assert contract.scene_topology == "light_table"
        assert any("PlaneGeometry" in p or "Texture" in p for p in contract.primitive_set)

    def test_no_identity_signals_returns_defaults_not_crash(self) -> None:
        contract = derive_geometry_contract(None, None, None)
        assert isinstance(contract, GeometryContractV1)
        assert contract.mode in GEOMETRY_MODES
        assert contract.composition_rules  # at least anti-portfolio rule
        assert contract.primitive_set

    def test_to_compact_dict_excludes_empty_fields(self) -> None:
        contract = derive_geometry_contract(
            {"tone_keywords": ["bold"]},
            {"themes": ["cinematic"], "complexity": "moderate"},
            {},
        )
        d = contract.to_compact_dict()
        # Empty lists should not appear
        for k, v in d.items():
            assert v not in ([], None, ""), f"Unexpected empty value for key {k!r}: {v!r}"

    def test_geometry_mode_is_always_valid(self) -> None:
        test_cases = [
            ({}, {"content_types": ["writing"]}, {}),
            ({"tone_keywords": ["minimal"]}, {"themes": ["systems", "network"]}, {}),
            ({}, {"content_types": ["art"], "themes": ["experimental"]}, {}),
            ({}, {}, {"experience_mode": "immersive_identity_experience"}),
        ]
        for ib, si, bs in test_cases:
            contract = derive_geometry_contract(ib, si, bs)
            assert contract.mode in GEOMETRY_MODES, f"Invalid mode {contract.mode!r} for {ib}, {si}, {bs}"

    def test_diagram_mode_has_diagram_relationship_mode(self) -> None:
        contract = derive_geometry_contract(
            {},
            {"content_types": ["data"], "themes": ["network", "connective"], "complexity": "ambitious"},
            {},
        )
        assert contract.mode == "diagram"
        assert contract.diagram_relationship_mode is not None
        assert "force" in contract.diagram_relationship_mode or "hierarchical" in contract.diagram_relationship_mode or "radial" in contract.diagram_relationship_mode

    def test_derivation_signals_present(self) -> None:
        contract = derive_geometry_contract(
            {"tone_keywords": ["cinematic"]},
            {"themes": ["cinematic"], "content_types": ["photography"], "complexity": "ambitious"},
            {},
        )
        assert contract.derivation_signals
        assert any("theme:" in s for s in contract.derivation_signals)
        assert any("mode:" in s for s in contract.derivation_signals)


# ---------------------------------------------------------------------------
# B. Scene Manifest V1 parsing and fingerprint computation
# ---------------------------------------------------------------------------


class TestSceneManifestV1:
    """SceneManifestV1 parsing, fingerprint, and evolution delta."""

    def test_parse_from_valid_raw_output(self) -> None:
        raw = {
            "kmbl_scene_manifest_v1": {
                "scene_metaphor": "light_table",
                "geometry_mode": "three",
                "primitive_set": ["PlaneGeometry", "TextureLoader"],
                "library_stack": ["three", "gsap"],
                "portfolio_shell_used": False,
                "identity_signals_used": ["photography", "cinematic"],
            },
            "artifact_outputs": [],
        }
        manifest = parse_scene_manifest_from_raw(raw)
        assert manifest is not None
        assert manifest.scene_metaphor == "light_table"
        assert manifest.geometry_mode == "three"
        assert "PlaneGeometry" in manifest.primitive_set
        assert not manifest.portfolio_shell_used
        # Fingerprint computed by parser when absent
        assert manifest.scene_fingerprint
        assert len(manifest.scene_fingerprint) == 12

    def test_parse_returns_none_when_absent(self) -> None:
        assert parse_scene_manifest_from_raw({}) is None
        assert parse_scene_manifest_from_raw(None) is None
        assert parse_scene_manifest_from_raw({"other_key": "x"}) is None

    def test_parse_tolerates_extra_fields(self) -> None:
        raw = {
            "kmbl_scene_manifest_v1": {
                "scene_metaphor": "signal_field",
                "geometry_mode": "three",
                "EXTRA_UNKNOWN_FIELD": "should_be_ignored",
                "library_stack": ["three"],
                "portfolio_shell_used": False,
            }
        }
        manifest = parse_scene_manifest_from_raw(raw)
        assert manifest is not None
        assert manifest.scene_metaphor == "signal_field"

    def test_fingerprint_is_deterministic(self) -> None:
        fp1 = build_scene_fingerprint_v1(
            geometry_mode="three",
            primitive_set=["PlaneGeometry", "TextureLoader"],
            scene_topology="light_table",
            library_stack=["three", "gsap"],
            h1_text="Hello World",
        )
        fp2 = build_scene_fingerprint_v1(
            geometry_mode="three",
            primitive_set=["TextureLoader", "PlaneGeometry"],  # order differs
            scene_topology="light_table",
            library_stack=["gsap", "three"],  # order differs
            h1_text="Hello World",
        )
        assert fp1 == fp2, "Fingerprint should be order-independent"

    def test_different_scenes_produce_different_fingerprints(self) -> None:
        fp_light = build_scene_fingerprint_v1(
            geometry_mode="three", scene_topology="light_table",
            library_stack=["three", "gsap"],
        )
        fp_signal = build_scene_fingerprint_v1(
            geometry_mode="three", scene_topology="signal_field",
            library_stack=["three", "gsap"],
        )
        assert fp_light != fp_signal

    def test_manifest_to_fingerprint_data_includes_key_fields(self) -> None:
        manifest = SceneManifestV1(
            scene_metaphor="light_table",
            geometry_mode="three",
            scene_topology="light_table",
            primitive_set=["PlaneGeometry"],
            library_stack=["three", "gsap"],
            identity_signals_used=["photography"],
            portfolio_shell_used=False,
            scene_fingerprint="abc123456789",
        )
        fp_data = manifest_to_fingerprint_data(manifest)
        assert fp_data["scene_fingerprint"] == "abc123456789"
        assert fp_data["geometry_mode"] == "three"
        assert "three" in fp_data["library_stack"]
        assert not fp_data["portfolio_shell_used"]

    def test_evolution_delta_flags_no_change(self) -> None:
        """Same scene repeated → weak_delta True."""
        manifest = SceneManifestV1(
            scene_metaphor="light_table",
            geometry_mode="three",
            scene_topology="light_table",
            library_stack=["three", "gsap"],
            portfolio_shell_used=False,
            scene_fingerprint="aabbccddeeff",
        )
        prior_fp_data = {
            "scene_fingerprint": "aabbccddeeff",  # same fingerprint
            "geometry_mode": "three",
            "library_stack": ["three", "gsap"],
            "primitive_set": [],
        }
        delta = compute_scene_evolution_delta(manifest, prior_fp_data)
        assert delta["weak_delta"] is True
        assert delta["delta_score"] == 0.0

    def test_evolution_delta_detects_meaningful_changes(self) -> None:
        """Changed geometry mode + library stack → weak_delta False."""
        manifest = SceneManifestV1(
            scene_metaphor="signal_field",
            geometry_mode="three",
            scene_topology="signal_field",
            library_stack=["three", "gsap"],
            composition_rules=["Particle scatter field", "No sections"],
            interaction_rules=["Pointer drives field density"],
            portfolio_shell_used=False,
            scene_fingerprint="newfingerprint",
        )
        prior_fp_data = {
            "scene_fingerprint": "oldfingerprint",
            "geometry_mode": "css_spatial",  # changed
            "scene_topology": "editorial_cosmos",  # changed
            "library_stack": ["gsap"],  # changed (no three)
            "primitive_set": [],
            "composition_rules": ["Old rule"],
            "interaction_rules": [],
        }
        delta = compute_scene_evolution_delta(manifest, prior_fp_data)
        assert delta["weak_delta"] is False
        assert len(delta["delta_categories"]) >= 2

    def test_evolution_delta_skips_when_no_prior(self) -> None:
        manifest = SceneManifestV1(geometry_mode="three", scene_fingerprint="abc")
        delta = compute_scene_evolution_delta(manifest, None)
        assert delta["skipped"] is True
        assert delta["delta_score"] is None
        assert not delta["weak_delta"]

    def test_fingerprint_from_summary_fields_stable(self) -> None:
        summary = {
            "libraries_detected": ["three", "gsap"],
            "sections_or_modules": {"h1_text": "Hello"},
            "interaction_summary": {"cues": ["js_events", "canvas_element"]},
            "experience_summary": {"experience_mode": "immersive_identity_experience"},
            "file_inventory": [{"path": "component/preview/index.html"}],
        }
        fp1 = build_fingerprint_from_summary_fields(summary)
        fp2 = build_fingerprint_from_summary_fields(summary)
        assert fp1 == fp2
        assert len(fp1) == 12


# ---------------------------------------------------------------------------
# C. Scene fingerprint persistence in build_candidate_summary_v1
# ---------------------------------------------------------------------------


class TestBuildCandidateSummarySceneFingerprint:
    """build_build_candidate_summary_v1 persists scene fingerprint and evolution delta."""

    def _make_artifact(self, content: str) -> dict:
        return {
            "role": "interactive_frontend_app_v1",
            "path": "component/preview/index.html",
            "content": content,
        }

    def test_summary_includes_scene_fingerprint_data(self) -> None:
        artifacts = [self._make_artifact(
            "<!DOCTYPE html><html><body>"
            "<script>import * as THREE from 'https://unpkg.com/three@0.158.0/build/three.module.js';"
            "document.addEventListener('click', () => {});</script></body></html>"
        )]
        summary = build_build_candidate_summary_v1(
            artifacts,
            build_spec={"type": "interactive_frontend_app_v1"},
            event_input={"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
        )
        assert "scene_fingerprint_data" in summary
        fp_data = summary["scene_fingerprint_data"]
        assert isinstance(fp_data, dict)
        assert "scene_fingerprint" in fp_data

    def test_summary_includes_scene_evolution_delta_when_prior_provided(self) -> None:
        artifact_content = (
            "<!DOCTYPE html><html><body>"
            "<script>const s = new THREE.Scene(); document.addEventListener('click', () => {});</script>"
            "</body></html>"
        )
        artifacts = [self._make_artifact(artifact_content)]

        # Build prior summary first
        prior_summary = build_build_candidate_summary_v1(
            [self._make_artifact("<html><body><script>window.gsap = {};</script></body></html>")],
            build_spec={"type": "interactive_frontend_app_v1"},
            event_input={},
        )
        # Ensure prior has a fingerprint
        assert prior_summary.get("scene_fingerprint_data")

        # Build current summary with prior provided
        current_summary = build_build_candidate_summary_v1(
            artifacts,
            build_spec={"type": "interactive_frontend_app_v1"},
            event_input={},
            prior_summary=prior_summary,
        )
        assert "scene_evolution_delta" in current_summary
        # delta should not be None when prior was provided
        evo = current_summary["scene_evolution_delta"]
        assert evo is not None

    def test_manifest_parsed_from_raw_generator_output(self) -> None:
        raw_output = {
            "kmbl_scene_manifest_v1": {
                "scene_metaphor": "light_table",
                "geometry_mode": "three",
                "library_stack": ["three", "gsap"],
                "portfolio_shell_used": False,
            }
        }
        artifacts = [self._make_artifact("<html><body></body></html>")]
        summary = build_build_candidate_summary_v1(
            artifacts,
            build_spec={"type": "interactive_frontend_app_v1"},
            event_input={},
            raw_generator_output=raw_output,
        )
        assert summary["scene_manifest_present"] is True
        assert "kmbl_scene_manifest_v1" in summary
        assert summary["kmbl_scene_manifest_v1"]["scene_metaphor"] == "light_table"

    def test_no_manifest_in_raw_gives_fallback_fingerprint(self) -> None:
        artifacts = [self._make_artifact("<html><body></body></html>")]
        summary = build_build_candidate_summary_v1(
            artifacts,
            build_spec={"type": "interactive_frontend_app_v1"},
            event_input={},
        )
        assert summary["scene_manifest_present"] is False
        assert "scene_fingerprint_data" in summary
        fp = summary["scene_fingerprint_data"]["scene_fingerprint"]
        assert isinstance(fp, str)


# ---------------------------------------------------------------------------
# D. Evolution delta gate using scene_evolution_delta — cannot silently skip
# ---------------------------------------------------------------------------


class TestEvolutionDeltaGateWiring:
    """Weak-delta gate fires from scene_evolution_delta in summary (durable path)."""

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

    def test_weak_delta_fires_from_scene_evolution_delta_in_summary(self) -> None:
        """Gate reads from scene_evolution_delta in summary — no prior fingerprint key needed."""
        report = self._make_report()
        bs = {
            "type": "interactive_frontend_app_v1",
            "title": "x",
            "steps": [],
            "execution_contract": {"required_interactions": [{"id": "scene", "mechanism": "js"}]},
        }
        bc = {
            "_kmbl_iteration_hint": 1,
            "artifact_outputs": [
                {
                    "role": "interactive_frontend_app_v1",
                    "path": "component/preview/index.html",
                    "content": (
                        "<!DOCTYPE html><html><body>"
                        "<script>document.addEventListener('click', () => {});</script>"
                        "</body></html>"
                    ),
                }
            ],
            "kmbl_build_candidate_summary_v1": {
                "scene_evolution_delta": {
                    "delta_categories": [],  # Nothing changed
                    "delta_score": 0.0,
                    "weak_delta": True,
                    "prior_fingerprint": "aabbccddeeff",
                    "current_fingerprint": "aabbccddeeff",
                    "skipped": False,
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
        assert WEAK_ITERATION_DELTA_CODE in codes
        delta = out.metrics_json.get("iteration_delta", {})
        assert delta.get("source") == "scene_evolution_delta"

    def test_strong_delta_does_not_fire_from_scene_evolution_delta(self) -> None:
        report = self._make_report()
        bs = {"type": "interactive_frontend_app_v1", "title": "x", "steps": []}
        bc = {
            "_kmbl_iteration_hint": 1,
            "artifact_outputs": [
                {
                    "role": "interactive_frontend_app_v1",
                    "path": "component/preview/index.html",
                    "content": (
                        "<html><body><script>window.addEventListener('scroll', () => {});</script></body></html>"
                    ),
                }
            ],
            "kmbl_build_candidate_summary_v1": {
                "scene_evolution_delta": {
                    "delta_categories": ["geometry_mode", "scene_topology", "library_stack"],
                    "delta_score": 0.43,
                    "weak_delta": False,
                    "prior_fingerprint": "old",
                    "current_fingerprint": "new",
                    "skipped": False,
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
        assert WEAK_ITERATION_DELTA_CODE not in codes

    def test_no_prior_data_does_not_fire_weak_delta(self) -> None:
        """When no prior data at all, cannot compute delta — gate must not fire."""
        report = self._make_report()
        bs = {"type": "interactive_frontend_app_v1", "title": "x", "steps": []}
        bc = {
            "_kmbl_iteration_hint": 1,
            "artifact_outputs": [
                {
                    "role": "interactive_frontend_app_v1",
                    "path": "component/preview/index.html",
                    "content": (
                        "<html><body><script>document.addEventListener('click', () => {});</script></body></html>"
                    ),
                }
            ],
            # No kmbl_build_candidate_summary_v1, no _kmbl_prior_candidate_fingerprint
        }
        out = apply_interactive_lane_evaluator_gate(
            report,
            build_spec=bs,
            event_input={"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
            build_candidate=bc,
        )
        codes = [i.get("code") for i in out.issues_json if isinstance(i, dict)]
        assert WEAK_ITERATION_DELTA_CODE not in codes

    def test_compact_scene_fingerprint_for_prior_extracts_from_summary(self) -> None:
        summary = {
            "scene_fingerprint_data": {
                "scene_fingerprint": "abc123456789",
                "geometry_mode": "three",
                "library_stack": ["three", "gsap"],
            }
        }
        result = compact_scene_fingerprint_for_prior(summary)
        assert result is not None
        assert result["scene_fingerprint"] == "abc123456789"

    def test_compact_scene_fingerprint_for_prior_returns_none_when_absent(self) -> None:
        assert compact_scene_fingerprint_for_prior(None) is None
        assert compact_scene_fingerprint_for_prior({}) is None


# ---------------------------------------------------------------------------
# E. Geometry-mode-driven library policy
# ---------------------------------------------------------------------------


class TestGeometryModeLibraryPolicy:
    """Library policy is correctly routed by geometry mode."""

    def test_three_mode_gives_three_gsap(self) -> None:
        policy = build_geometry_mode_library_policy("three")
        assert "three" in policy["primary_stack"]
        assert "gsap" in policy["primary_stack"]

    def test_diagram_mode_gives_d3(self) -> None:
        policy = build_geometry_mode_library_policy("diagram")
        assert "d3" in policy["primary_stack"]

    def test_svg_mode_gives_svg_js(self) -> None:
        policy = build_geometry_mode_library_policy("svg")
        assert "svg.js" in policy["primary_stack"]

    def test_pixi_mode_gives_pixi(self) -> None:
        policy = build_geometry_mode_library_policy("pixi")
        assert "pixi" in policy["primary_stack"]

    def test_babylon_mode_gives_babylon(self) -> None:
        policy = build_geometry_mode_library_policy("babylon")
        assert "babylon" in policy["primary_stack"]

    def test_all_geometry_modes_have_policy(self) -> None:
        from kmbl_orchestrator.contracts.geometry_contract_v1 import GEOMETRY_MODES
        for mode in GEOMETRY_MODES:
            policy = build_geometry_mode_library_policy(mode)
            assert policy["primary_stack"], f"Empty primary_stack for mode {mode!r}"

    def test_anti_patterns_present_in_policy(self) -> None:
        policy = build_geometry_mode_library_policy("three")
        assert "anti_patterns" in policy
        assert len(policy["anti_patterns"]) > 0

    def test_generator_anti_patterns_constant_non_empty(self) -> None:
        assert len(GENERATOR_ANTI_PATTERNS) >= 3
        assert any("TorusKnot" in p for p in GENERATOR_ANTI_PATTERNS)

    def test_geometry_lane_libraries_includes_d3_and_svg(self) -> None:
        assert "d3" in GEOMETRY_LANE_LIBRARIES
        assert "svg.js" in GEOMETRY_LANE_LIBRARIES
        assert "jointjs" in GEOMETRY_LANE_LIBRARIES

    def test_geometry_mode_library_recommendations_from_contract(self) -> None:
        recs = geometry_mode_to_library_recommendations("diagram")
        assert recs["geometry_mode"] == "diagram"
        assert "d3" in recs["primary_stack"]
        assert recs["anti_patterns"]

    def test_unknown_mode_falls_back_to_three(self) -> None:
        policy = build_geometry_mode_library_policy("UNKNOWN_MODE")
        assert "three" in policy["primary_stack"]


# ---------------------------------------------------------------------------
# F. Non-portfolio immersive runs use geometry contract without portfolio sections
# ---------------------------------------------------------------------------


class TestGeometryContractInCoolLane:
    """Cool lane presets inject geometry contract and do not force portfolio sections."""

    def test_cool_lane_injects_geometry_system_into_execution_contract(self) -> None:
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
        identity_brief = {"tone_keywords": ["cinematic", "dark"], "aesthetic_keywords": ["noir"]}
        structured_identity = {"content_types": ["photography"], "themes": ["cinematic"], "complexity": "ambitious"}

        result, meta = apply_cool_generation_lane_presets(bs, event_input, identity_brief, structured_identity)

        ec = result.get("execution_contract", {})
        assert "geometry_system" in ec, "geometry_system must be in execution_contract"
        geo = ec["geometry_system"]
        assert "mode" in geo
        assert "composition_rules" in geo
        assert "motion_mapping_rules" in geo
        assert meta["geometry_contract_applied"] is True

    def test_cool_lane_geometry_mode_in_meta(self) -> None:
        bs = {
            "type": "interactive_frontend_app_v1",
            "title": "Studio",
            "steps": [],
            "experience_mode": "immersive_identity_experience",
        }
        event_input = {"cool_generation_lane": True, "constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}
        _, meta = apply_cool_generation_lane_presets(bs, event_input, None, None)
        assert "geometry_mode" in meta
        assert meta["geometry_mode"] in GEOMETRY_MODES

    def test_cool_lane_no_portfolio_sections_with_geometry_system(self) -> None:
        bs = {
            "type": "interactive_frontend_app_v1",
            "title": "Experimental",
            "steps": [],
            "experience_mode": "immersive_identity_experience",
            "site_archetype": "experimental",
        }
        event_input = {"cool_generation_lane": True, "constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}
        result, _ = apply_cool_generation_lane_presets(bs, event_input, None, None)
        ec = result.get("execution_contract", {})
        required = ec.get("required_sections") or []
        portfolio = {"hero", "projects", "about", "contact", "proof_or_work"}
        assert not (portfolio & set(required)), f"Got portfolio sections: {required}"

    def test_cool_lane_generator_payload_includes_geometry_system(self) -> None:
        """summarize_execution_contract_for_generator surfaces geometry_system."""
        from kmbl_orchestrator.runtime.cool_generation_lane import summarize_execution_contract_for_generator
        bs = {
            "type": "interactive_frontend_app_v1",
            "title": "x",
            "steps": [],
            "execution_contract": {
                "lane": "cool_generation_v1",
                "geometry_system": {
                    "mode": "three",
                    "primitive_set": ["PlaneGeometry"],
                    "composition_rules": ["No portfolio sections"],
                },
            },
        }
        summary = summarize_execution_contract_for_generator(bs)
        assert "geometry_system" in summary
        assert summary["geometry_system"]["mode"] == "three"

    def test_cool_lane_allowed_libraries_aligned_with_geometry_mode(self) -> None:
        """For diagram mode, allowed_libraries should include d3."""
        bs = {
            "type": "interactive_frontend_app_v1",
            "title": "Network",
            "steps": [],
            "experience_mode": "immersive_identity_experience",
        }
        event_input = {"cool_generation_lane": True, "constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}
        identity_brief = {"tone_keywords": ["precise"]}
        structured_identity = {"content_types": ["data", "network"], "themes": ["network", "systems"], "complexity": "ambitious"}
        result, meta = apply_cool_generation_lane_presets(bs, event_input, identity_brief, structured_identity)
        ec = result.get("execution_contract", {})
        if meta["geometry_mode"] == "diagram":
            # Libraries should be aligned with diagram mode
            libs = ec.get("allowed_libraries", [])
            assert "d3" in libs or "three" in libs  # d3 preferred for diagram mode


# ---------------------------------------------------------------------------
# G. Compact prompt strategy: geometry_system is machine-readable, not only prose
# ---------------------------------------------------------------------------


class TestCompactPromptStrategy:
    """Geometry contract provides machine-readable rules, not just creative adjectives."""

    def test_geometry_contract_is_compact_json_serializable(self) -> None:
        import json
        contract = derive_geometry_contract(
            {"tone_keywords": ["cinematic"], "aesthetic_keywords": ["dark"]},
            {"content_types": ["photography"], "themes": ["cinematic"], "complexity": "ambitious"},
            {"experience_mode": "immersive_identity_experience", "creative_brief": {"scene_metaphor": "light_table"}},
        )
        d = contract.to_compact_dict()
        # Must be JSON serializable
        serialized = json.dumps(d)
        assert len(serialized) < 2000, f"Geometry contract too large for prompt: {len(serialized)} chars"

    def test_geometry_contract_fields_are_machine_readable(self) -> None:
        """Fields should be lists/strings, not long prose paragraphs."""
        contract = derive_geometry_contract(
            {"tone_keywords": ["experimental"]},
            {"themes": ["experimental"], "complexity": "ambitious"},
            {},
        )
        # primitive_set should be short tokens, not sentences
        for prim in contract.primitive_set:
            assert len(prim) < 60, f"Primitive set item too long: {prim!r}"

        # composition_rules should be imperative sentences, not paragraphs
        for rule in contract.composition_rules:
            assert len(rule) < 120, f"Composition rule too long: {rule!r}"

    def test_scene_manifest_fingerprint_is_12_chars(self) -> None:
        fp = build_scene_fingerprint_v1(
            geometry_mode="three",
            scene_topology="light_table",
            library_stack=["three", "gsap"],
        )
        assert len(fp) == 12

    def test_evolution_categories_count_reasonable(self) -> None:
        """EVOLUTION_CATEGORIES should be a reasonable number (not too few, not too many)."""
        assert 5 <= len(EVOLUTION_CATEGORIES) <= 12

    def test_geometry_mode_library_map_covers_all_modes(self) -> None:
        from kmbl_orchestrator.contracts.geometry_contract_v1 import GEOMETRY_MODES
        for mode in GEOMETRY_MODES:
            assert mode in GEOMETRY_MODE_LIBRARY_MAP, f"Mode {mode!r} missing from GEOMETRY_MODE_LIBRARY_MAP"
            libs = GEOMETRY_MODE_LIBRARY_MAP[mode]
            assert libs, f"Mode {mode!r} has empty library list"
