"""Generator-side gallery variation preset — bounded inputs, generator payload wiring."""

from __future__ import annotations

from kmbl_orchestrator.contracts.role_inputs import GeneratorRoleInput, validate_role_input
from kmbl_orchestrator.seeds import (
    SEEDED_GALLERY_STRIP_EVENT_INPUT,
    SEEDED_GALLERY_STRIP_VARIED_SCENARIO_PRESET,
    SEEDED_GALLERY_STRIP_VARIED_SCENARIO_TAG,
    build_seeded_gallery_strip_varied_v1_event_input,
)


def test_deterministic_gallery_seed_unchanged() -> None:
    assert SEEDED_GALLERY_STRIP_EVENT_INPUT["constraints"]["deterministic"] is True
    assert "variation" not in SEEDED_GALLERY_STRIP_EVENT_INPUT


def test_varied_preset_includes_bounded_variation_and_not_deterministic() -> None:
    a = build_seeded_gallery_strip_varied_v1_event_input(run_nonce="nonce_alpha")
    b = build_seeded_gallery_strip_varied_v1_event_input(run_nonce="nonce_beta")
    assert a["scenario"] == SEEDED_GALLERY_STRIP_VARIED_SCENARIO_TAG
    assert a["constraints"]["deterministic"] is False
    assert a["constraints"]["gallery_variation_mode"] == "explicit_bounded"
    v = a["variation"]
    assert v["run_nonce"] == "nonce_alpha"
    assert isinstance(v["variation_seed"], int)
    for k in ("theme_variant", "subject_variant", "layout_variant", "tone_variant"):
        assert k in v and isinstance(v[k], str) and v[k]
    assert b["variation"]["run_nonce"] == "nonce_beta"
    # Different nonces → different seeds (extremely likely; fixed strings differ in hash)
    assert a["variation"]["variation_seed"] != b["variation"]["variation_seed"]


def test_varied_preset_constant_name_matches_api() -> None:
    assert SEEDED_GALLERY_STRIP_VARIED_SCENARIO_PRESET == "seeded_gallery_strip_varied_v1"


def test_resolve_start_applies_varied_preset() -> None:
    from kmbl_orchestrator.api.main import StartRunBody, _resolve_start_event_input

    ev, preset = _resolve_start_event_input(
        StartRunBody(scenario_preset="seeded_gallery_strip_varied_v1")
    )
    assert preset == SEEDED_GALLERY_STRIP_VARIED_SCENARIO_PRESET
    assert ev["scenario"] == SEEDED_GALLERY_STRIP_VARIED_SCENARIO_TAG
    assert ev["constraints"]["deterministic"] is False
    assert "variation" in ev


def test_generator_role_input_accepts_event_input_for_variation() -> None:
    ei = build_seeded_gallery_strip_varied_v1_event_input(run_nonce="fixed_test_nonce")
    raw = validate_role_input(
        "generator",
        {
            "thread_id": "00000000-0000-0000-0000-000000000001",
            "build_spec": {"title": "t"},
            "current_working_state": {},
            "iteration_feedback": None,
            "event_input": ei,
        },
    )
    assert raw["event_input"]["variation"]["run_nonce"] == "fixed_test_nonce"
    model = GeneratorRoleInput.model_validate(raw)
    assert model.event_input["scenario"] == SEEDED_GALLERY_STRIP_VARIED_SCENARIO_TAG
