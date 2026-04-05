"""Tests for neutralized bundle seed prompt and planner type-selection observability."""

from __future__ import annotations

from kmbl_orchestrator.runtime.run_events import RunEventType
from kmbl_orchestrator.seeds import (
    build_identity_url_bundle_event_input,
    build_identity_url_static_frontend_event_input,
)
from kmbl_orchestrator.runtime.cool_generation_lane import (
    summarize_execution_contract_for_generator,
)


# ── Bundle seed neutrality ──────────────────────────────────────────────


def test_bundle_seed_task_does_not_contain_prefer_static() -> None:
    """The bundle seed must not contain a soft static bias."""
    ei = build_identity_url_bundle_event_input(identity_url="https://example.com")
    task = ei["task"]
    assert "Prefer static" not in task
    assert "prefer static" not in task.lower() or "prefer static when" not in task.lower()


def test_bundle_seed_task_mentions_both_verticals_neutrally() -> None:
    """Bundle seed must describe both static and interactive without favoring either."""
    ei = build_identity_url_bundle_event_input(identity_url="https://example.com")
    task = ei["task"]
    assert "static_frontend_file_v1" in task
    assert "interactive_frontend_app_v1" in task
    # Both verticals should have clear use-case descriptions, not just one
    assert "editorial" in task.lower() or "text-first" in task.lower()
    assert "interaction" in task.lower() or "motion" in task.lower()


def test_bundle_seed_encourages_creative_brief() -> None:
    """Bundle seed should prompt for creative_brief fields."""
    ei = build_identity_url_bundle_event_input(identity_url="https://example.com")
    task = ei["task"]
    assert "creative_brief" in task


def test_bundle_seed_no_canonical_vertical_pin() -> None:
    """Bundle seed must not contain canonical_vertical in constraints."""
    ei = build_identity_url_bundle_event_input(identity_url="https://example.com")
    cons = ei.get("constraints", {})
    assert "canonical_vertical" not in cons
    assert cons.get("kmbl_frontend_vertical_policy") == "planner_choice"


def test_static_seed_still_pins_canonical_vertical() -> None:
    """Static seed must still pin canonical_vertical (unchanged)."""
    ei = build_identity_url_static_frontend_event_input(identity_url="https://example.com")
    cons = ei.get("constraints", {})
    assert cons["canonical_vertical"] == "static_frontend_file_v1"
    assert cons["kmbl_static_frontend_vertical"] is True


# ── Planner vertical observability event type ────────────────────────────


def test_planner_vertical_selected_event_type_exists() -> None:
    """RunEventType.PLANNER_VERTICAL_SELECTED must be defined."""
    assert hasattr(RunEventType, "PLANNER_VERTICAL_SELECTED")
    assert RunEventType.PLANNER_VERTICAL_SELECTED == "planner_vertical_selected"


# ── Generator brief richness ─────────────────────────────────────────────


def test_summarize_execution_contract_includes_creative_direction() -> None:
    """The generator contract summary must surface creative brief fields."""
    build_spec = {
        "type": "interactive_frontend_app_v1",
        "execution_contract": {
            "allowed_libraries": ["three.js", "gsap"],
            "required_interactions": [
                {"id": "orbit_control"},
                {"id": "color_toggle"},
            ],
        },
        "creative_brief": {
            "mood": "dark_cinematic",
            "direction_summary": "Noir-inspired 3D portfolio with floating geometry",
            "color_strategy": "deep blacks, neon accent",
            "layout_concept": "single-scroll immersive canvas",
            "interaction_goals": "orbit camera + project reveal on click",
        },
        "literal_success_checks": ["three.js", "canvas"],
    }
    summary = summarize_execution_contract_for_generator(build_spec)

    # Creative direction fields surfaced
    assert summary["creative_brief_mood"] == "dark_cinematic"
    assert summary["creative_brief_direction_summary"] == "Noir-inspired 3D portfolio with floating geometry"
    assert summary["creative_brief_color_strategy"] == "deep blacks, neon accent"
    assert summary["creative_brief_layout_concept"] == "single-scroll immersive canvas"
    assert summary["creative_brief_interaction_goals"] == "orbit camera + project reveal on click"

    # Library and interaction awareness
    assert summary["allowed_libraries"] == ["three.js", "gsap"]
    assert summary["required_interactions_count"] == 2

    # Existing fields preserved
    assert summary["literal_success_checks_count"] == 2


def test_summarize_execution_contract_graceful_with_missing_brief() -> None:
    """Summary must not crash when creative_brief is absent."""
    build_spec = {
        "type": "static_frontend_file_v1",
    }
    summary = summarize_execution_contract_for_generator(build_spec)
    assert summary["creative_brief_mood"] is None
    assert summary["creative_brief_direction_summary"] is None
    assert summary["creative_brief_color_strategy"] is None
    assert summary["creative_brief_layout_concept"] is None
    assert summary["creative_brief_interaction_goals"] is None
    assert summary["allowed_libraries"] is None
    assert summary["required_interactions_count"] == 0


def test_summarize_execution_contract_empty_build_spec() -> None:
    """Edge case: completely empty build_spec."""
    summary = summarize_execution_contract_for_generator({})
    assert summary["creative_brief_mood"] is None
    assert summary["literal_success_checks_count"] == 0
    assert summary["required_interactions_count"] == 0
