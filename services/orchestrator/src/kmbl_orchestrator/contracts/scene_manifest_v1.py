"""
Scene Manifest V1 — structured output emitted by the generator describing the actual scene built.

This is the primary grounding signal for evaluator novelty/identity checks.
It replaces best-effort HTML comment scraping as the source of truth for:
  - what geometry mode was used
  - what primitives were chosen
  - whether portfolio shell was used
  - which identity signals drove choices
  - a deterministic fingerprint for iteration delta

Generator emits ``kmbl_scene_manifest_v1`` at the top level of its JSON output.
Orchestrator parses, persists, and passes to the evaluator as structured facts.
HTML comment markers (<!-- kmbl-scene-metaphor: ... -->) remain as secondary hints.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Scene Manifest V1 model
# ---------------------------------------------------------------------------


class SceneManifestV1(BaseModel):
    """
    Structured declaration of what scene the generator actually built.

    Generator emits this at the top level of its JSON response as ``kmbl_scene_manifest_v1``.
    Orchestrator validates, persists in build candidate summary, and passes to evaluator.
    """

    model_config = ConfigDict(extra="ignore")

    # Scene intent
    scene_metaphor: str = ""
    geometry_mode: str = ""
    scene_topology: str | None = None

    # What was actually used
    primitive_set: list[str] = Field(default_factory=list)
    composition_rules: list[str] = Field(default_factory=list)
    interaction_rules: list[str] = Field(default_factory=list)
    library_stack: list[str] = Field(default_factory=list)

    # Identity grounding evidence
    identity_signals_used: list[str] = Field(default_factory=list)

    # Evolution gating
    scene_fingerprint: str = ""
    portfolio_shell_used: bool = False

    # Structured scene/canvas manifest signals (preferred by evaluator when present)
    lane_mix: dict[str, Any] = Field(default_factory=dict)
    canvas_model: dict[str, Any] = Field(default_factory=dict)
    media_transformation_summary: dict[str, Any] = Field(default_factory=dict)
    source_transformation_summary: dict[str, Any] = Field(default_factory=dict)
    identity_abstraction_summary: dict[str, Any] = Field(default_factory=dict)

    # Self-reported delta from prior (optional — generator may populate)
    claimed_delta_from_prior: str | None = None


# ---------------------------------------------------------------------------
# Scene fingerprint computation
# ---------------------------------------------------------------------------


def build_scene_fingerprint_v1(
    *,
    geometry_mode: str = "",
    primitive_set: list[str] | None = None,
    scene_topology: str | None = None,
    library_stack: list[str] | None = None,
    composition_rules: list[str] | None = None,
    h1_text: str = "",
    section_ids: list[str] | None = None,
    interaction_cues: list[str] | None = None,
) -> str:
    """
    Compute a deterministic 12-char scene fingerprint from normalized scene components.

    Stable across minor whitespace/order variations; sensitive to meaningful structural changes.
    Used for iteration delta detection: if fingerprint matches prior, no real evolution happened.
    """
    # Normalize all lists to sorted, lowercase, stripped
    def _norm(lst: list[str] | None) -> list[str]:
        return sorted({str(x).strip().lower() for x in (lst or []) if x})

    canonical = {
        "geometry_mode": str(geometry_mode or "").strip().lower(),
        "primitive_set": _norm(primitive_set),
        "scene_topology": str(scene_topology or "").strip().lower(),
        "library_stack": _norm(library_stack),
        "composition_rules_digest": hashlib.sha256(
            json.dumps(sorted({str(r).strip().lower()[:60] for r in (composition_rules or [])})).encode()
        ).hexdigest()[:8],
        "h1_text": str(h1_text or "").strip().lower()[:80],
        "section_ids": _norm(section_ids),
        "interaction_cues": _norm(interaction_cues),
    }
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def build_fingerprint_from_manifest(manifest: SceneManifestV1) -> str:
    """Build fingerprint from a SceneManifestV1 instance."""
    return build_scene_fingerprint_v1(
        geometry_mode=manifest.geometry_mode,
        primitive_set=manifest.primitive_set,
        scene_topology=manifest.scene_topology,
        library_stack=manifest.library_stack,
        composition_rules=manifest.composition_rules,
    )


def build_fingerprint_from_summary_fields(
    summary: dict[str, Any],
) -> str:
    """
    Build a fingerprint from a build_candidate_summary_v1 dict.

    Used when the generator did not emit a scene manifest — fallback fingerprint
    from artifact-observable signals.
    """
    libs = sorted(summary.get("libraries_detected") or [])
    outline = summary.get("sections_or_modules") or {}
    h1 = str(outline.get("h1_text") or "").strip().lower()[:80]
    cues = sorted((summary.get("interaction_summary") or {}).get("cues") or [])
    em = str((summary.get("experience_summary") or {}).get("experience_mode") or "")
    inv = summary.get("file_inventory") or []
    paths = sorted({str(r.get("path", "")).replace("\\", "/") for r in inv if isinstance(r, dict)})
    return build_scene_fingerprint_v1(
        geometry_mode=em,
        library_stack=libs,
        h1_text=h1,
        interaction_cues=cues,
        # section_ids from file paths (rough)
        section_ids=paths[:8],
    )


# ---------------------------------------------------------------------------
# Parse scene manifest from raw generator output
# ---------------------------------------------------------------------------


def parse_scene_manifest_from_raw(
    raw_generator_output: dict[str, Any] | None,
) -> SceneManifestV1 | None:
    """
    Extract and validate a SceneManifestV1 from the generator's raw JSON output.

    Returns None when the generator did not emit ``kmbl_scene_manifest_v1``.
    Validates via Pydantic; ignores extra fields gracefully.
    """
    if not isinstance(raw_generator_output, dict):
        return None
    raw_manifest = raw_generator_output.get("kmbl_scene_manifest_v1")
    if not isinstance(raw_manifest, dict):
        return None
    try:
        manifest = SceneManifestV1.model_validate(raw_manifest)
    except Exception:
        return None
    # Compute fingerprint if not provided by generator
    if not manifest.scene_fingerprint:
        manifest = manifest.model_copy(
            update={"scene_fingerprint": build_fingerprint_from_manifest(manifest)}
        )
    return manifest


# ---------------------------------------------------------------------------
# Scene evolution delta
# ---------------------------------------------------------------------------


#: Categories used for evolution scoring.
EVOLUTION_CATEGORIES = (
    "geometry_mode",
    "scene_topology",
    "library_stack",
    "primitive_set_digest",
    "composition_rules_digest",
    "h1_text",
    "portfolio_shell",
    "interaction_rules_digest",
)


def compute_scene_evolution_delta(
    current: SceneManifestV1 | None,
    prior_fingerprint_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Compute a structured evolution delta between current manifest and prior fingerprint data.

    ``prior_fingerprint_data`` is the ``scene_fingerprint_data`` dict stored in the prior
    build_candidate_summary_v1.  Returns a dict with:
      - delta_categories: list of what changed
      - delta_score: float 0.0-1.0 (fraction of categories changed)
      - weak_delta: bool (True when delta_score < 0.33)
      - prior_fingerprint: str (the prior fingerprint hash)
      - current_fingerprint: str
    """
    if current is None or prior_fingerprint_data is None:
        return {
            "delta_categories": [],
            "delta_score": None,
            "weak_delta": False,
            "prior_fingerprint": None,
            "current_fingerprint": current.scene_fingerprint if current else None,
            "skipped": True,
        }

    prior_fp = str(prior_fingerprint_data.get("scene_fingerprint") or "")
    current_fp = current.scene_fingerprint

    # Fast path: if fingerprints match, nothing changed
    if prior_fp and current_fp and prior_fp == current_fp:
        return {
            "delta_categories": [],
            "delta_score": 0.0,
            "weak_delta": True,
            "prior_fingerprint": prior_fp,
            "current_fingerprint": current_fp,
            "skipped": False,
        }

    changed: list[str] = []

    def _norm_set(lst: list[str] | None) -> frozenset[str]:
        return frozenset(str(x).strip().lower() for x in (lst or []))

    # geometry_mode
    prior_mode = str(prior_fingerprint_data.get("geometry_mode") or "").lower()
    if prior_mode and prior_mode != current.geometry_mode.lower():
        changed.append("geometry_mode")

    # scene_topology
    prior_topo = str(prior_fingerprint_data.get("scene_topology") or "").lower()
    curr_topo = str(current.scene_topology or "").lower()
    if prior_topo and prior_topo != curr_topo:
        changed.append("scene_topology")

    # library_stack
    prior_libs = _norm_set(prior_fingerprint_data.get("library_stack") or [])
    curr_libs = _norm_set(current.library_stack)
    if prior_libs and prior_libs != curr_libs:
        changed.append("library_stack")

    # primitive_set (digest comparison)
    prior_prims = _norm_set(prior_fingerprint_data.get("primitive_set") or [])
    curr_prims = _norm_set(current.primitive_set)
    if prior_prims and prior_prims != curr_prims:
        changed.append("primitive_set")

    # portfolio_shell
    prior_shell = bool(prior_fingerprint_data.get("portfolio_shell_used"))
    curr_shell = current.portfolio_shell_used
    if prior_shell != curr_shell:
        changed.append("portfolio_shell")

    # composition rules (rough string comparison)
    prior_comp = _norm_set(prior_fingerprint_data.get("composition_rules") or [])
    curr_comp = _norm_set(current.composition_rules)
    if prior_comp and prior_comp != curr_comp:
        changed.append("composition_rules")

    # interaction rules
    prior_inter = _norm_set(prior_fingerprint_data.get("interaction_rules") or [])
    curr_inter = _norm_set(current.interaction_rules)
    if prior_inter and prior_inter != curr_inter:
        changed.append("interaction_rules")

    total_categories = len(EVOLUTION_CATEGORIES)
    delta_score = round(len(changed) / total_categories, 3)
    weak_delta = delta_score < (1.0 / total_categories) * 2  # < 2 categories changed

    return {
        "delta_categories": changed,
        "delta_score": delta_score,
        "weak_delta": weak_delta,
        "prior_fingerprint": prior_fp or None,
        "current_fingerprint": current_fp,
        "skipped": False,
    }


# ---------------------------------------------------------------------------
# Compact fingerprint data dict (persisted in summary)
# ---------------------------------------------------------------------------


def manifest_to_fingerprint_data(manifest: SceneManifestV1) -> dict[str, Any]:
    """
    Extract a compact, serializable fingerprint data dict from a manifest.

    This is persisted in build_candidate_summary_v1 so the NEXT iteration can
    compare against it.  Lightweight: no full content, just key structural signals.
    """
    return {
        "scene_fingerprint": manifest.scene_fingerprint,
        "geometry_mode": manifest.geometry_mode,
        "scene_topology": manifest.scene_topology,
        "library_stack": sorted(str(x).strip().lower() for x in manifest.library_stack),
        "primitive_set": sorted(str(x).strip().lower() for x in manifest.primitive_set)[:6],
        "composition_rules": [str(r).strip().lower()[:60] for r in manifest.composition_rules[:4]],
        "interaction_rules": [str(r).strip().lower()[:60] for r in manifest.interaction_rules[:3]],
        "portfolio_shell_used": manifest.portfolio_shell_used,
        "identity_signals_used": manifest.identity_signals_used[:6],
        "lane_mix": {
            "primary_lane": str((manifest.lane_mix or {}).get("primary_lane") or "")[:48],
            "secondary_lanes": [str(x)[:48] for x in ((manifest.lane_mix or {}).get("secondary_lanes") or [])[:3]],
        },
        "canvas_model": {
            "zone_model": str((manifest.canvas_model or {}).get("zone_model") or "")[:48],
            "surface_type": str((manifest.canvas_model or {}).get("surface_type") or "")[:32],
            "media_modes": [str(x)[:32] for x in ((manifest.canvas_model or {}).get("media_modes") or [])[:5]],
        },
    }


__all__ = [
    "EVOLUTION_CATEGORIES",
    "SceneManifestV1",
    "build_fingerprint_from_manifest",
    "build_fingerprint_from_summary_fields",
    "build_scene_fingerprint_v1",
    "compute_scene_evolution_delta",
    "manifest_to_fingerprint_data",
    "parse_scene_manifest_from_raw",
]
