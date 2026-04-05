"""Map ``StartRunBody`` to ``event_input`` — no graph/langgraph imports (test-friendly)."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.api.models import StartRunBody
from kmbl_orchestrator.seeds import (
    IDENTITY_URL_BUNDLE_PRESET,
    IDENTITY_URL_STATIC_FRONTEND_PRESET,
    KILOCLAW_IMAGE_ONLY_TEST_EVENT_INPUT,
    KILOCLAW_IMAGE_ONLY_TEST_SCENARIO_PRESET,
    SEEDED_GALLERY_STRIP_EVENT_INPUT,
    SEEDED_GALLERY_STRIP_SCENARIO_PRESET,
    SEEDED_GALLERY_STRIP_VARIED_SCENARIO_PRESET,
    SEEDED_LOCAL_EVENT_INPUT,
    SEEDED_LOCAL_SCENARIO_PRESET,
    build_identity_url_bundle_event_input,
    build_identity_url_static_frontend_event_input,
    build_seeded_gallery_strip_varied_v1_event_input,
    merge_identity_url_bundle_extras,
    merge_identity_url_static_frontend_extras,
)


def resolve_start_event_input(
    body: StartRunBody,
    *,
    identity_seed_summary: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Map ``StartRunBody`` + optional identity summary to ``event_input`` and optional preset tag."""
    if body.scenario_preset == SEEDED_LOCAL_SCENARIO_PRESET:
        return dict(SEEDED_LOCAL_EVENT_INPUT), SEEDED_LOCAL_SCENARIO_PRESET
    if body.scenario_preset == SEEDED_GALLERY_STRIP_SCENARIO_PRESET:
        return dict(SEEDED_GALLERY_STRIP_EVENT_INPUT), SEEDED_GALLERY_STRIP_SCENARIO_PRESET
    if body.scenario_preset == SEEDED_GALLERY_STRIP_VARIED_SCENARIO_PRESET:
        return (
            build_seeded_gallery_strip_varied_v1_event_input(),
            SEEDED_GALLERY_STRIP_VARIED_SCENARIO_PRESET,
        )
    if body.scenario_preset == KILOCLAW_IMAGE_ONLY_TEST_SCENARIO_PRESET:
        return (
            dict(KILOCLAW_IMAGE_ONLY_TEST_EVENT_INPUT),
            KILOCLAW_IMAGE_ONLY_TEST_SCENARIO_PRESET,
        )

    if body.scenario_preset == IDENTITY_URL_STATIC_FRONTEND_PRESET:
        url = body.identity_url or ""
        built = build_identity_url_static_frontend_event_input(
            identity_url=url,
            seed_summary=identity_seed_summary,
        )
        merged = merge_identity_url_static_frontend_extras(built, body.event_input)
        return merged, IDENTITY_URL_STATIC_FRONTEND_PRESET

    if body.scenario_preset == IDENTITY_URL_BUNDLE_PRESET or body.identity_url:
        url = body.identity_url or ""
        built = build_identity_url_bundle_event_input(
            identity_url=url,
            seed_summary=identity_seed_summary,
        )
        merged = merge_identity_url_bundle_extras(built, body.event_input)
        return merged, IDENTITY_URL_BUNDLE_PRESET

    return dict(body.event_input), None
