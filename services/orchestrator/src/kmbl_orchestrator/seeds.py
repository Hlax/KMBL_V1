"""Canonical local dev seeds for graph runs (deterministic, inspectable)."""

from __future__ import annotations

import hashlib
import secrets
from typing import Any, Final

# --- Canonical vertical: identity URL → static frontend (explicit opt-in) ---
IDENTITY_URL_STATIC_FRONTEND_PRESET: Final = "identity_url_static_v1"
IDENTITY_URL_STATIC_FRONTEND_TAG: Final = "kmbl_identity_url_static_v1"

# --- Default identity URL path: planner may choose static or interactive bundle (no early canonical_vertical pin) ---
IDENTITY_URL_BUNDLE_PRESET: Final = "identity_url_bundle_v1"
IDENTITY_URL_BUNDLE_TAG: Final = "kmbl_identity_url_bundle_v1"

# API: POST /orchestrator/runs/start with {"scenario_preset": "seeded_local_v1"}
SEEDED_LOCAL_SCENARIO_PRESET: Final = "seeded_local_v1"

# Embedded in event_input so run snapshots / status can tag the scenario.
SEEDED_SCENARIO_TAG: Final = "kmbl_seeded_local_v1"

# Second preset: POST /orchestrator/runs/start with {"scenario_preset": "seeded_gallery_strip_v1"}
SEEDED_GALLERY_STRIP_SCENARIO_PRESET: Final = "seeded_gallery_strip_v1"
SEEDED_GALLERY_STRIP_SCENARIO_TAG: Final = "kmbl_seeded_gallery_strip_v1"

# Non-deterministic local gallery — distinct preset; new run_nonce per API resolution.
SEEDED_GALLERY_STRIP_VARIED_SCENARIO_PRESET: Final = "seeded_gallery_strip_varied_v1"
SEEDED_GALLERY_STRIP_VARIED_SCENARIO_TAG: Final = "kmbl_seeded_gallery_strip_varied_v1"

# KiloClaw image agent only (kmbl-image-gen via routing) — 3–4 generated gallery_strip_image_v1 rows required.
KILOCLAW_IMAGE_ONLY_TEST_SCENARIO_PRESET: Final = "kiloclaw_image_only_test_v1"
KILOCLAW_IMAGE_ONLY_TEST_SCENARIO_TAG: Final = "kmbl_kiloclaw_image_only_test_v1"

# Bounded vocabulary — selection uses (variation_seed + salt * 31) % len; auditable.
GALLERY_VARIATION_THEME_VARIANTS: Final[tuple[str, ...]] = (
    "daylight",
    "nocturne",
    "pastel",
    "high_contrast",
)
GALLERY_VARIATION_SUBJECT_VARIANTS: Final[tuple[str, ...]] = (
    "abstract",
    "architecture",
    "nature_study",
    "portrait_study",
)
GALLERY_VARIATION_LAYOUT_VARIANTS: Final[tuple[str, ...]] = (
    "strip_4",
    "strip_5",
    "strip_6",
    "featured_left",
)
GALLERY_VARIATION_TONE_VARIANTS: Final[tuple[str, ...]] = (
    "neutral",
    "playful",
    "editorial_minimal",
    "bold_caption",
)

# Planner receives this via state["event_input"] — aim for a concrete mini-plan, not a no-op.
SEEDED_LOCAL_EVENT_INPUT: dict[str, Any] = {
    "scenario": SEEDED_SCENARIO_TAG,
    "task": (
        "Produce a small build_spec for a local KMBL verification run: three numbered steps "
        "(health check, start persisted run, fetch run status) with short titles and one-line "
        "descriptions each. Include at least two success_criteria strings and one "
        "evaluation_targets entry referencing the checklist quality."
    ),
    "constraints": {
        "style": "numbered_checklist",
        "scope": "local_dev_only",
        "deterministic": True,
    },
}

KILOCLAW_IMAGE_ONLY_TEST_EVENT_INPUT: dict[str, Any] = {
    "scenario": KILOCLAW_IMAGE_ONLY_TEST_SCENARIO_TAG,
    "task": (
        "Integration test: **three or four** distinct `gallery_strip_image_v1` rows in artifact_outputs "
        "with real generated URLs from the image pipeline (OpenClaw kmbl-image-gen). "
        "Planner: build_spec must require gallery images and list success criteria. "
        "Generator: emit `artifact_outputs`, `updated_state.ui_gallery_strip_v1`, and `proposed_changes`; "
        "do not use placeholder image hosts. If images cannot be produced, surface failure in output — "
        "do not substitute fake URLs. "
        "Evaluator: FAIL if fewer than three `gallery_strip_image_v1` artifacts or any missing URLs."
    ),
    "constraints": {
        "style": "integration_test",
        "scope": "kiloclaw_image_agent_only",
        "deterministic": True,
        "ui_surface": "gallery_strip_v1",
        "required_gallery_image_count_min": 3,
        "required_gallery_image_count_max": 4,
        "disallow_placeholder_image_hosts": True,
    },
}

# Gallery strip UI experiment — generator must emit updated_state["ui_gallery_strip_v1"] only.
SEEDED_GALLERY_STRIP_EVENT_INPUT: dict[str, Any] = {
    "scenario": SEEDED_GALLERY_STRIP_SCENARIO_TAG,
    "task": (
        "Bounded UI experiment: control-plane gallery strip only (single surface). "
        "Planner: build_spec type/title reference this gallery strip experiment — not whole-app "
        "HTML or arbitrary files. "
        "Generator: set updated_state to exactly one key, ui_gallery_strip_v1, with optional "
        "headline and items (1–6). Each item: label (required), optional caption, optional "
        "href as http(s), and either image_url (direct) or image_artifact_key referencing "
        "artifact_outputs entries with role gallery_strip_image_v1 (key, url, optional "
        "thumb_url, alt, source generated|external|upload). Persisted artifacts are reviewable "
        "in staging alongside the strip. "
        "Do not put other keys in updated_state for this run. "
        "Evaluator: judge readability, URL safety, and coherence between strip items and images."
    ),
    "constraints": {
        "style": "numbered_checklist",
        "scope": "local_dev_only",
        "deterministic": True,
        "ui_surface": "gallery_strip_v1",
    },
}


def _pick_bounded_variant(options: tuple[str, ...], variation_seed: int, salt: int) -> str:
    idx = (variation_seed + salt * 31) % len(options)
    return options[idx]


def build_seeded_gallery_strip_varied_v1_event_input(*, run_nonce: str | None = None) -> dict[str, Any]:
    """
    Local gallery run with explicit bounded variation (not deterministic).

    Each call assigns a fresh ``run_nonce`` unless one is passed (tests / replay).
    ``variation_seed`` is derived from ``run_nonce`` so the same nonce reproduces the same picks.
    """
    nonce = run_nonce if run_nonce is not None else secrets.token_hex(8)
    digest = hashlib.sha256(f"kmbl:gallery_varied_v1:{nonce}".encode("utf-8")).digest()
    variation_seed = int.from_bytes(digest[:4], "big") % (2**31)

    theme_variant = _pick_bounded_variant(GALLERY_VARIATION_THEME_VARIANTS, variation_seed, 1)
    subject_variant = _pick_bounded_variant(GALLERY_VARIATION_SUBJECT_VARIANTS, variation_seed, 2)
    layout_variant = _pick_bounded_variant(GALLERY_VARIATION_LAYOUT_VARIANTS, variation_seed, 3)
    tone_variant = _pick_bounded_variant(GALLERY_VARIATION_TONE_VARIANTS, variation_seed, 4)

    task = (
        "Varied gallery-strip UI experiment (local dev only). Same contract as deterministic "
        "seeded_gallery_strip_v1, but this run is **not** deterministic. "
        "Planner: build_spec must reference this gallery-strip experiment. "
        "Generator: read **event_input** (also passed on the generator payload as `event_input`) "
        "and honor **variation** — choose distinct strip content and **gallery_strip_image_v1** "
        "artifacts that reflect theme_variant, subject_variant, layout_variant, and tone_variant; "
        "do **not** reuse the same image URLs/keys as another run when run_nonce differs unless "
        "upstream constraints or a documented fallback force it. "
        "Emit updated_state with exactly one key: ui_gallery_strip_v1 (headline optional, 1–6 items). "
        "Each item: label (required), optional caption, optional href http(s), and either image_url "
        "or image_artifact_key referencing artifact_outputs with role gallery_strip_image_v1. "
        "layout_variant hints item count emphasis (e.g. strip_4 → four items). "
        "Do not add other keys to updated_state. "
        "Evaluator: judge coherence between variation and the strip."
    )

    return {
        "scenario": SEEDED_GALLERY_STRIP_VARIED_SCENARIO_TAG,
        "task": task,
        "constraints": {
            "style": "numbered_checklist",
            "scope": "local_dev_only",
            "deterministic": False,
            "ui_surface": "gallery_strip_v1",
            "gallery_variation_mode": "explicit_bounded",
        },
        "variation": {
            "run_nonce": nonce,
            "variation_seed": variation_seed,
            "theme_variant": theme_variant,
            "subject_variant": subject_variant,
            "layout_variant": layout_variant,
            "tone_variant": tone_variant,
        },
    }


def build_identity_url_static_frontend_event_input(
    *, identity_url: str, seed_summary: str | None = None
) -> dict[str, Any]:
    """
    Canonical vertical event_input: identity URL → static frontend.

    The planner receives identity_context with rich signals and makes all creative decisions.
    No hardcoded variants - the planner interprets the identity and designs accordingly.
    """
    seed_hint = f" ({seed_summary})" if seed_summary else ""

    task = (
        f"Build a static website reflecting the identity from {identity_url}{seed_hint}. "
        "Planner: analyze identity_context (profile_summary, facets) and make creative decisions "
        "in build_spec (design_direction, layout_concept, color_strategy). "
        "Generator: execute the planner's vision with static_frontend_file_v1 artifacts. "
        "Output must include artifact_outputs with at least one HTML file."
    )
    return {
        "scenario": IDENTITY_URL_STATIC_FRONTEND_TAG,
        "task": task,
        "identity_url": identity_url,
        "constraints": {
            "canonical_vertical": "static_frontend_file_v1",
            "kmbl_static_frontend_vertical": True,
            "scope": "identity_url_vertical",
            "deterministic": False,
            "planner_is_creative_director": True,
        },
    }


def build_identity_url_bundle_event_input(
    *, identity_url: str, seed_summary: str | None = None
) -> dict[str, Any]:
    """
    Identity URL vertical without pinning ``canonical_vertical`` to static.

    The planner sets ``build_spec.type`` to ``static_frontend_file_v1`` or
    ``interactive_frontend_app_v1`` (and matching constraints when needed) based on
    identity_context, crawl_context, and creative intent. The orchestrator does not
    force static before planning; ``clamp_experience_mode_for_static_vertical`` applies
    only when the effective vertical is static.
    """
    seed_hint = f" ({seed_summary})" if seed_summary else ""

    task = (
        f"Build a frontend reflecting the identity from {identity_url}{seed_hint}. "
        "Planner: analyze identity_context, crawl_context, and structured_identity to choose "
        "the build_spec.type that best serves the identity's goals, visual ambition, and "
        "interaction needs — while keeping scope controlled. "
        "Use static_frontend_file_v1 for text-first editorial or portfolio pages where layout "
        "and typography carry the design. "
        "Use interactive_frontend_app_v1 when the identity signals spatial/motion/3D ambition, "
        "meaningful user interaction, or a multi-file component structure (organized JS/CSS, "
        "light Three.js, canvas, or scroll-driven motion) that clearly improves the product. "
        "Generator: honor build_spec.type — produce artifact_outputs (and/or workspace ingest) "
        "matching the chosen vertical. Include build_spec.creative_brief with design_direction, "
        "color_strategy, layout_concept, and interaction_goals so the generator has rich context."
    )
    return {
        "scenario": IDENTITY_URL_BUNDLE_TAG,
        "task": task,
        "identity_url": identity_url,
        "constraints": {
            "scope": "identity_url_vertical",
            "deterministic": False,
            "planner_is_creative_director": True,
            "kmbl_frontend_vertical_policy": "planner_choice",
            "kmbl_interactive_bundle_guardrails": {
                "max_component_files_soft_cap": 24,
                "avoid_heavy_runtime": True,
            },
        },
    }


# Keys owned by build_identity_url_static_frontend_event_input — extras must not replace them.
IDENTITY_URL_PRESET_CANONICAL_KEYS: Final = frozenset(
    ("scenario", "task", "identity_url", "constraints")
)


def merge_identity_url_static_frontend_extras(
    built: dict[str, Any],
    event_input: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge caller extras (e.g. cool_generation_lane) without replacing the canonical seed dict."""
    if not event_input:
        return built
    extras = {
        k: v
        for k, v in event_input.items()
        if k not in IDENTITY_URL_PRESET_CANONICAL_KEYS
    }
    return {**built, **extras}


def merge_identity_url_bundle_extras(
    built: dict[str, Any],
    event_input: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge caller extras for the bundle identity seed (same canonical-key protection as static)."""
    if not event_input:
        return built
    extras = {
        k: v
        for k, v in event_input.items()
        if k not in IDENTITY_URL_PRESET_CANONICAL_KEYS
    }
    return {**built, **extras}
