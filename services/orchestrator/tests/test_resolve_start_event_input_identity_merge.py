"""Identity URL preset must merge extras (e.g. cool_generation_lane) from StartRunBody.event_input."""

from __future__ import annotations

from kmbl_orchestrator.api.models import StartRunBody
from kmbl_orchestrator.application.start_event_input_resolution import resolve_start_event_input
from kmbl_orchestrator.seeds import (
    IDENTITY_URL_BUNDLE_TAG,
    IDENTITY_URL_STATIC_FRONTEND_TAG,
    SEEDED_SCENARIO_TAG,
    build_identity_url_bundle_event_input,
    build_identity_url_static_frontend_event_input,
    merge_identity_url_static_frontend_extras,
)


def test_merge_preserves_cool_generation_lane() -> None:
    built = build_identity_url_static_frontend_event_input(
        identity_url="https://harveylacsina.com/",
        seed_summary="harvey lacsina",
    )
    merged = merge_identity_url_static_frontend_extras(
        built,
        {"cool_generation_lane": True},
    )
    assert merged["scenario"] == IDENTITY_URL_STATIC_FRONTEND_TAG
    assert merged["cool_generation_lane"] is True
    assert merged["identity_url"] == "https://harveylacsina.com/"


def test_merge_does_not_let_event_input_override_canonical_keys() -> None:
    built = build_identity_url_static_frontend_event_input(identity_url="https://example.com/")
    merged = merge_identity_url_static_frontend_extras(
        built,
        {
            "cool_generation_lane": True,
            "scenario": "wrong_scenario",
            "task": "wrong",
            "constraints": {"bogus": True},
        },
    )
    assert merged["scenario"] == IDENTITY_URL_STATIC_FRONTEND_TAG
    assert merged["cool_generation_lane"] is True
    assert merged["constraints"]["canonical_vertical"] == "static_frontend_file_v1"


def test_resolve_identity_url_defaults_to_bundle_not_static() -> None:
    ev, preset = resolve_start_event_input(
        StartRunBody(identity_url="https://example.com/"),
        identity_seed_summary=None,
    )
    assert preset == "identity_url_bundle_v1"
    assert ev.get("scenario") == IDENTITY_URL_BUNDLE_TAG
    assert "canonical_vertical" not in (ev.get("constraints") or {})


def test_resolve_seeded_local_wins_over_identity_url() -> None:
    """identity_url must not override an explicit seeded preset (ordering fix)."""
    ev, preset = resolve_start_event_input(
        StartRunBody(
            identity_url="https://example.com/",
            scenario_preset="seeded_local_v1",
        ),
    )
    assert preset == "seeded_local_v1"
    assert ev.get("scenario") == SEEDED_SCENARIO_TAG


def test_resolve_explicit_static_preset_still_pins_static() -> None:
    ev, preset = resolve_start_event_input(
        StartRunBody(
            identity_url="https://example.com/",
            scenario_preset="identity_url_static_v1",
        ),
    )
    assert preset == "identity_url_static_v1"
    assert ev.get("scenario") == IDENTITY_URL_STATIC_FRONTEND_TAG
    assert ev["constraints"]["canonical_vertical"] == "static_frontend_file_v1"


def test_bundle_merge_preserves_cool_generation_lane() -> None:
    from kmbl_orchestrator.seeds import merge_identity_url_bundle_extras

    built = build_identity_url_bundle_event_input(identity_url="https://example.com/")
    merged = merge_identity_url_bundle_extras(built, {"cool_generation_lane": True})
    assert merged["scenario"] == IDENTITY_URL_BUNDLE_TAG
    assert merged["cool_generation_lane"] is True


def test_interactive_vertical_detection_after_planner_choice() -> None:
    """Sanity: bundle seed does not set static flags; planner can select interactive."""
    from kmbl_orchestrator.runtime.static_vertical_invariants import (
        is_interactive_frontend_vertical,
        is_static_frontend_vertical,
    )

    ei = build_identity_url_bundle_event_input(identity_url="https://x.com")
    assert not is_static_frontend_vertical({}, ei)
    assert not is_interactive_frontend_vertical({}, ei)
    bs = {"type": "interactive_frontend_app_v1", "title": "t", "steps": []}
    assert is_interactive_frontend_vertical(bs, ei)
    assert not is_static_frontend_vertical(bs, ei)
