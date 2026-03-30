"""Canonical local dev seeds for graph runs (deterministic, inspectable)."""

from __future__ import annotations

import hashlib
import secrets
from typing import Any, Final

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
