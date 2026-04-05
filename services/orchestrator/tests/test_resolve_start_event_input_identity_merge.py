"""Identity URL preset must merge extras (e.g. cool_generation_lane) from StartRunBody.event_input."""

from __future__ import annotations

from kmbl_orchestrator.seeds import (
    IDENTITY_URL_STATIC_FRONTEND_TAG,
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
