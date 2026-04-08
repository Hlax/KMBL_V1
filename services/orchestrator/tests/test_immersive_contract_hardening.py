from __future__ import annotations

from kmbl_orchestrator.runtime.immersive_contract_hardening import (
    harden_immersive_planner_output,
)


def test_hardens_portfolio_shell_defaults_for_immersive_runs() -> None:
    raw = {
        "build_spec": {
            "type": "interactive_frontend_app_v1",
            "experience_mode": "immersive_identity_experience",
            "site_archetype": "immersive_brand_world",
            "creative_brief": {
                "layout_concept": "Hero with projects grid, about timeline, and contact CTA.",
                "scene_metaphor": "kinetic light tunnel",
            },
            "execution_contract": {
                "layout_mode": "stacked_sections",
                "required_sections": ["hero", "projects_grid", "about_timeline", "contact_cta"],
                "allowed_libraries": ["three", "gsap"],
            },
        },
        "steps": [
            {"title": "Hero section", "description": "Add a hero"},
            {"title": "Projects grid", "description": "Show case studies"},
            {"title": "About section", "description": "Describe the team"},
        ],
        "success_criteria": ["Hero is visible", "Projects grid renders", "Contact section is present"],
        "evaluation_targets": [
            {"kind": "selector_present", "selector": "#hero"},
            {"kind": "selector_present", "selector": ".projects-grid"},
        ],
    }

    out, meta = harden_immersive_planner_output(raw, event_input={})

    assert meta is not None
    execution_contract = out["build_spec"]["execution_contract"]
    assert execution_contract["layout_mode"] == "immersive_single_surface"
    assert execution_contract["required_sections"] == [
        "primary_surface",
        "spatial_layers",
        "interaction_layer",
    ]
    assert execution_contract["session_delivery_strategy"] == "single_surface_session"
    assert execution_contract["canvas_system"]["zone_model"] == "single_scene"
    assert out["steps"][0]["title"] == "Primary immersive surface"
    assert all("hero" not in item.lower() for item in out["success_criteria"])
    assert all(target.get("selector") != "#hero" for target in out["evaluation_targets"] if isinstance(target, dict))


def test_leaves_non_immersive_build_spec_untouched() -> None:
    raw = {
        "build_spec": {
            "type": "interactive_frontend_app_v1",
            "experience_mode": "editorial_storytelling",
            "creative_brief": {"layout_concept": "Structured story page"},
            "execution_contract": {"layout_mode": "stacked_sections"},
        },
        "success_criteria": ["Narrative sections are readable"],
    }
    out, meta = harden_immersive_planner_output(raw, event_input={})
    assert meta is None
    assert out == raw