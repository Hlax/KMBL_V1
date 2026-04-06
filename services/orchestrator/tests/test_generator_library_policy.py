"""KMBL frontend generation library policy — defaults, escalation, lane context."""

from __future__ import annotations

from kmbl_orchestrator.contracts.static_frontend_artifact_v1 import StaticFrontendFileArtifactV1
from kmbl_orchestrator.contracts.interactive_build_spec_v1 import (
    apply_interactive_build_spec_hardening,
)
from kmbl_orchestrator.runtime.generator_library_policy import (
    GAUSSIAN_SPLAT_ESCALATION_LANE,
    GAUSSIAN_SPLAT_LIBRARY_PRIMARY,
    PRIMARY_LANE_DEFAULT_LIBRARIES,
    build_generator_library_policy_payload,
)
from kmbl_orchestrator.runtime.interactive_lane_context import build_interactive_lane_context
from kmbl_orchestrator.runtime.reference_patterns import (
    build_library_compliance_hints,
    select_reference_patterns,
)


def test_default_allowed_libraries_are_three_gsap() -> None:
    bs: dict = {"type": "interactive_frontend_app_v1", "title": "t", "steps": []}
    _, meta = apply_interactive_build_spec_hardening(
        bs,
        {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
    )
    assert meta.interactive_vertical is True
    libs = bs["execution_contract"]["allowed_libraries"]
    assert libs[:2] == ["three", "gsap"]
    assert "pixi" not in libs
    assert "allowed_libraries_defaulted_primary_lane" in meta.fixes


def test_heavy_webgl_appends_wgsl_not_default_for_flat_mode() -> None:
    bs_flat: dict = {
        "type": "interactive_frontend_app_v1",
        "title": "t",
        "steps": [],
        "experience_mode": "flat_standard",
        "execution_contract": {},
    }
    apply_interactive_build_spec_hardening(
        bs_flat,
        {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
    )
    assert "wgsl" not in bs_flat["execution_contract"]["allowed_libraries"]

    bs_heavy: dict = {
        "type": "interactive_frontend_app_v1",
        "title": "t",
        "steps": [],
        "experience_mode": "webgl_3d_portfolio",
        "execution_contract": {},
    }
    _, meta_h = apply_interactive_build_spec_hardening(
        bs_heavy,
        {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
    )
    assert "wgsl" in bs_heavy["execution_contract"]["allowed_libraries"]
    assert "allowed_libraries_appended_wgsl_for_heavy_webgl_ambition" in meta_h.fixes


def test_planner_explicit_libraries_not_replaced_with_defaults() -> None:
    bs: dict = {
        "type": "interactive_frontend_app_v1",
        "title": "t",
        "steps": [],
        "execution_contract": {"allowed_libraries": ["pixi"]},
    }
    _, meta = apply_interactive_build_spec_hardening(
        bs,
        {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
    )
    assert bs["execution_contract"]["allowed_libraries"][0] == "pixi"
    assert "allowed_libraries_defaulted_primary_lane" not in meta.fixes


def test_generator_library_policy_payload_flags() -> None:
    ec = {"allowed_libraries": ["three", "gsap", "pixi"]}
    build_spec = {"experience_mode": "flat_standard"}
    p = build_generator_library_policy_payload(ec, build_spec)
    assert p["primary_lane_defaults"] == list(PRIMARY_LANE_DEFAULT_LIBRARIES)
    assert p["heavy_webgpu_wgsl_ambition_experience_mode"] is False
    assert p["flags"]["contract_includes_pixi"] is True
    assert ".wgsl" in p["allowed_shader_file_extensions"]
    assert p["policy_version"] == 2
    assert p["gaussian_splat_lane"]["primary_library"] == GAUSSIAN_SPLAT_LIBRARY_PRIMARY


def test_gaussian_splat_escalation_merges_libraries() -> None:
    bs: dict = {
        "type": "interactive_frontend_app_v1",
        "title": "t",
        "steps": [],
        "execution_contract": {"escalation_lane": GAUSSIAN_SPLAT_ESCALATION_LANE},
    }
    _, meta = apply_interactive_build_spec_hardening(
        bs,
        {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
    )
    libs = bs["execution_contract"]["allowed_libraries"]
    assert GAUSSIAN_SPLAT_LIBRARY_PRIMARY in libs
    assert "three" in libs
    assert "allowed_libraries_merged_for_gaussian_splat_lane" in meta.fixes


def test_select_reference_patterns_default_lane() -> None:
    ec = {"allowed_libraries": ["three", "gsap"]}
    bs = {"type": "interactive_frontend_app_v1", "experience_mode": "flat_standard"}
    pats = select_reference_patterns(ec, bs)
    assert len(pats) == 3
    assert all(x["lane"] == "default_three_gsap" for x in pats)


def test_select_reference_patterns_gaussian_only() -> None:
    ec = {
        "allowed_libraries": ["three", "gsap", GAUSSIAN_SPLAT_LIBRARY_PRIMARY],
        "escalation_lane": GAUSSIAN_SPLAT_ESCALATION_LANE,
    }
    bs = {"type": "interactive_frontend_app_v1"}
    pats = select_reference_patterns(ec, bs)
    assert len(pats) == 2
    assert all(x["lane"] == "gaussian_splat" for x in pats)


def test_compliance_hints_splat_library_without_escalation_lane() -> None:
    ec = {"allowed_libraries": [GAUSSIAN_SPLAT_LIBRARY_PRIMARY, "three"]}
    hints = build_library_compliance_hints(ec, {"type": "interactive_frontend_app_v1"})
    codes = [h["code"] for h in hints]
    assert "gaussian_splat_library_without_escalation_lane" in codes


def test_interactive_lane_context_includes_policy_and_escalation_tiers() -> None:
    ctx = build_interactive_lane_context(
        {
            "type": "interactive_frontend_app_v1",
            "experience_mode": "flat_standard",
            "execution_contract": {"allowed_libraries": ["three", "gsap"]},
        },
        {},
    )
    assert "generator_library_policy" in ctx
    assert "reference_patterns" in ctx
    assert "library_compliance_hints" in ctx
    assert ctx["generator_library_policy"]["heavy_webgpu_wgsl_ambition_experience_mode"] is False
    assert "escalation_lanes" in ctx["interactivity_tiers"]
    assert "pixi" in str(ctx["interactivity_tiers"]["escalation_lanes"]).lower()


def test_shader_vert_frag_paths_accepted() -> None:
    v = StaticFrontendFileArtifactV1.model_validate(
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/pass.vert",
            "language": "vert",
            "content": "void main() {}",
        }
    )
    assert v.language == "vert"
    f = StaticFrontendFileArtifactV1.model_validate(
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/pass.frag",
            "language": "frag",
            "content": "void main() {}",
        }
    )
    assert f.language == "frag"


def test_splat_ply_paths_accepted() -> None:
    s = StaticFrontendFileArtifactV1.model_validate(
        {
            "role": "static_frontend_file_v1",
            "path": "component/assets/scene.splat",
            "language": "splat",
            "content": "x",
        }
    )
    assert s.language == "splat"


def test_interactive_lane_context_not_heavy_implies_no_wgsl_default() -> None:
    ctx = build_interactive_lane_context(
        {
            "type": "interactive_frontend_app_v1",
            "experience_mode": "flat_standard",
            "execution_contract": {"allowed_libraries": ["three", "gsap"]},
        },
        {},
    )
    pol = ctx["generator_library_policy"]
    assert pol["webgpu_wgsl_in_contract"] is False

