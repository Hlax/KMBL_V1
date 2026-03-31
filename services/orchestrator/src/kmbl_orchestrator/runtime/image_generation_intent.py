"""
Explicit image-generation intent for KMBL generator OpenClaw routing.

Only **narrow, v1-stable signals** count (artifact ids, seeded scenarios, structured hooks).
Do **not** infer image work from vague aesthetic language or generic UI copy.

To add a new image-producing artifact type: extend ``KNOWN_IMAGE_ARTIFACT_IDS_V1`` and,
if needed, add a dedicated ``route_reason`` branch—routing logic stays in
``kilo_model_routing.select_generator_provider_config``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Iterator

from kmbl_orchestrator.seeds import (
    KILOCLAW_IMAGE_ONLY_TEST_SCENARIO_TAG,
    SEEDED_GALLERY_STRIP_SCENARIO_TAG,
    SEEDED_GALLERY_STRIP_VARIED_SCENARIO_TAG,
)

# Explicit v1 artifact role ids — extend here; no fuzzy or aesthetic matching.
KNOWN_IMAGE_ARTIFACT_IDS_V1: Final[frozenset[str]] = frozenset(
    {
        "gallery_strip_image_v1",
        "hero_banner_image_v1",  # non-gallery example surface; same routing policy
    }
)

# Substrings in evaluation_targets / success_criteria that imply image artifact work (explicit).
_IMAGE_CRITERIA_MARKERS: Final[tuple[str, ...]] = (
    "gallery_strip_image_v1",
    "gallery_strip_image",
    "ui_gallery_strip",
    "hero_banner_image_v1",
)


@dataclass(frozen=True)
class ImageGenerationIntent:
    """Structured intent; ``kind`` is ``\"none\"`` when no explicit image-generation request."""

    kind: str
    route_reason: str


def _iter_strings_from_artifact_outputs(items: Any) -> Iterator[str]:
    if not isinstance(items, list):
        return
    for x in items:
        if isinstance(x, str):
            yield x
        elif isinstance(x, dict):
            for k in ("role", "artifact_id", "type", "key"):
                v = x.get(k)
                if isinstance(v, str):
                    yield v


def _first_matching_artifact_id(strings: Iterator[str]) -> str | None:
    for s in strings:
        if s in KNOWN_IMAGE_ARTIFACT_IDS_V1:
            return s
    return None


def _artifact_outputs_from(d: dict[str, Any]) -> Any:
    return d.get("artifact_outputs")


def _is_static_frontend_vertical(ev: dict[str, Any], bs: dict[str, Any]) -> bool:
    """Identity URL → static HTML vertical; must not route to image agent from criteria wording."""
    c = ev.get("constraints")
    if isinstance(c, dict):
        if (
            c.get("canonical_vertical") == "static_frontend_file_v1"
            and c.get("kmbl_static_frontend_vertical") is True
        ):
            return True
    st = str(bs.get("type") or "").lower()
    if st == "static_frontend_file_v1":
        return True
    return False


def extract_image_generation_intent(
    *,
    event_input: dict[str, Any],
    build_spec: dict[str, Any],
    generator_payload: dict[str, Any] | None = None,
) -> ImageGenerationIntent:
    """
    Return explicit image-generation intent or ``kind=\"none\"``.

    Checks ``build_spec``, top-level ``generator_payload`` artifact lists, and
    ``generator_payload[\"build_spec\"]`` when present.
    """
    ev = event_input or {}
    bs = build_spec or {}
    gp = generator_payload or {}

    blobs: list[tuple[str, dict[str, Any]]] = [("build_spec", bs)]
    if isinstance(gp, dict):
        blobs.append(("generator_payload", gp))
        nbs = gp.get("build_spec")
        if isinstance(nbs, dict):
            blobs.append(("generator_payload.build_spec", nbs))

    # Static frontend vertical: only explicit artifact_outputs (image roles) may route to
    # kmbl-image-gen. Skip scenario tags, ui_surface, build_spec type heuristics, and
    # success_criteria substring markers — planners often mention "gallery" / markers in prose.
    if _is_static_frontend_vertical(ev, bs):
        for source_name, blob in blobs:
            ao = _artifact_outputs_from(blob)
            matched = _first_matching_artifact_id(_iter_strings_from_artifact_outputs(ao))
            if matched:
                return ImageGenerationIntent(
                    kind=matched,
                    route_reason=f"artifact_outputs_explicit:{source_name}",
                )
        return ImageGenerationIntent(
            kind="none",
            route_reason="static_frontend_vertical_no_explicit_image_artifacts",
        )

    # 1) Explicit artifact_outputs (narrow id match)
    for source_name, blob in blobs:
        ao = _artifact_outputs_from(blob)
        matched = _first_matching_artifact_id(_iter_strings_from_artifact_outputs(ao))
        if matched:
            return ImageGenerationIntent(
                kind=matched,
                route_reason=f"artifact_outputs_explicit:{source_name}",
            )

    # 2) Seeded gallery strip scenarios (canonical tags)
    scenario = str(ev.get("scenario") or "")
    if scenario == KILOCLAW_IMAGE_ONLY_TEST_SCENARIO_TAG:
        return ImageGenerationIntent(
            kind="gallery_strip_image_v1",
            route_reason="kiloclaw_image_only_test_v1",
        )

    if scenario in (
        SEEDED_GALLERY_STRIP_SCENARIO_TAG,
        SEEDED_GALLERY_STRIP_VARIED_SCENARIO_TAG,
    ):
        return ImageGenerationIntent(
            kind="gallery_strip_image_v1",
            route_reason="seeded_gallery_strip_scenario",
        )

    # 3) Structured constraint hook
    cons = ev.get("constraints")
    if isinstance(cons, dict) and cons.get("ui_surface") == "gallery_strip_v1":
        return ImageGenerationIntent(
            kind="gallery_strip_image_v1",
            route_reason="constraints_ui_surface_gallery_strip_v1",
        )

    # 4) build_spec.type gallery+strip (legacy structured)
    st = str(bs.get("type") or "").lower()
    if "gallery" in st and "strip" in st:
        return ImageGenerationIntent(
            kind="gallery_strip_image_v1",
            route_reason="build_spec_type_gallery_strip",
        )

    # 5) Explicit strings in evaluation_targets / success_criteria only
    for key in ("evaluation_targets", "success_criteria"):
        arr = bs.get(key)
        if not isinstance(arr, list):
            continue
        for item in arr:
            s = str(item).lower()
            for marker in _IMAGE_CRITERIA_MARKERS:
                if marker in s:
                    return ImageGenerationIntent(
                        kind="gallery_strip_image_v1",
                        route_reason=f"build_spec_{key}_explicit_marker",
                    )

    return ImageGenerationIntent(kind="none", route_reason="no_explicit_image_generation_intent")


def is_image_generation_request(
    *,
    event_input: dict[str, Any],
    build_spec: dict[str, Any],
    generator_payload: dict[str, Any] | None = None,
) -> bool:
    return (
        extract_image_generation_intent(
            event_input=event_input,
            build_spec=build_spec,
            generator_payload=generator_payload,
        ).kind
        != "none"
    )


def should_use_openai_for_image_generation(
    *,
    event_input: dict[str, Any],
    build_spec: dict[str, Any],
    generator_payload: dict[str, Any] | None = None,
) -> bool:
    """True only when explicit image-generation intent is present (same as ``is_image_generation_request``)."""
    return is_image_generation_request(
        event_input=event_input,
        build_spec=build_spec,
        generator_payload=generator_payload,
    )


__all__ = [
    "KNOWN_IMAGE_ARTIFACT_IDS_V1",
    "ImageGenerationIntent",
    "extract_image_generation_intent",
    "is_image_generation_request",
    "should_use_openai_for_image_generation",
]
