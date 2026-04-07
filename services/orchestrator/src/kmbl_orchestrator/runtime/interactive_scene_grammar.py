"""
Identity-to-scene translation layer for interactive/WebGL lanes.

Maps structured identity signals (tone, aesthetic, content_types, themes)
to concrete creative grammar that shapes the generator's 3D scene, motion
language, materials, and composition — so interactive builds feel
identity-derived rather than tutorial-derived.

Used by cool_generation_lane.py to inject identity-grounded creative direction
into the execution contract's creative brief.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Scene metaphor registry
# ---------------------------------------------------------------------------
# Each entry: (match_signals: set, scene_metaphor: str, description: str)
# Evaluated in priority order; first match wins.

_SCENE_METAPHOR_RULES: list[tuple[frozenset[str], frozenset[str], str, str]] = [
    # (content_signals, theme_signals, scene_metaphor, one_line_description)
    (
        frozenset({"photography"}),
        frozenset({"cinematic"}),
        "light_table",
        "Illuminated surface; images float as developed stills under raking light.",
    ),
    (
        frozenset({"photography"}),
        frozenset({"artistic", "experimental"}),
        "darkroom",
        "High-contrast photographic space; images emerge from dark field.",
    ),
    (
        frozenset({"design", "art"}),
        frozenset({"experimental"}),
        "studio_table",
        "Work surface scattered with artefacts; geometry as maker's tools.",
    ),
    (
        frozenset({"writing"}),
        frozenset({"cinematic", "artistic"}),
        "text_archive",
        "Layered typographic field; words as spatial objects in depth.",
    ),
    (
        frozenset({"art"}),
        frozenset({"experimental", "artistic"}),
        "signal_field",
        "Electromagnetic / particle metaphor; identity as a field not a grid.",
    ),
    (
        frozenset(),
        frozenset({"cinematic"}),
        "narrative_cinema",
        "Sequential spatial vignettes; viewer moves through scenes not sections.",
    ),
    (
        frozenset(),
        frozenset({"experimental"}),
        "installation_field",
        "Viewer placed inside a spatial installation; objects respond to presence.",
    ),
    (
        frozenset({"design"}),
        frozenset(),
        "grid_space",
        "Modular spatial grid; design sensibility expressed as structure.",
    ),
    (
        frozenset(),
        frozenset({"artistic"}),
        "object_theater",
        "Objects on a stage; identity items become 3D props with theatrical light.",
    ),
]

_DEFAULT_SCENE_METAPHOR = "editorial_cosmos"
_DEFAULT_SCENE_METAPHOR_DESC = "Spaced elements in a vast field; restrained editorial with depth."


def _pick_scene_metaphor(
    content_types: set[str],
    themes: set[str],
) -> tuple[str, str]:
    """Return (scene_metaphor, description) from identity signals."""
    for ct_signals, theme_signals, metaphor, desc in _SCENE_METAPHOR_RULES:
        ct_match = not ct_signals or bool(content_types & ct_signals)
        theme_match = not theme_signals or bool(themes & theme_signals)
        if ct_match and theme_match:
            return metaphor, desc
    return _DEFAULT_SCENE_METAPHOR, _DEFAULT_SCENE_METAPHOR_DESC


# ---------------------------------------------------------------------------
# Motion language mapping
# ---------------------------------------------------------------------------

_MOTION_LANGUAGE_MAP: dict[str, str] = {
    # tone_keyword → motion_language
    "bold": "precise_drift",
    "confident": "precise_drift",
    "restrained": "slow_drift",
    "controlled": "precise_drift",
    "warm": "gentle_spring",
    "organic": "gentle_spring",
    "human": "gentle_spring",
    "experimental": "reactive_field",
    "kinetic": "reactive_field",
    "dynamic": "reactive_field",
    "minimal": "immediate",
    "clinical": "immediate",
    "sharp": "immediate",
    "poetic": "slow_dissolve",
    "soft": "slow_dissolve",
    "meditative": "slow_dissolve",
    "dark": "slow_drift",
    "moody": "slow_drift",
}

_MOTION_LANGUAGE_DESCRIPTIONS: dict[str, str] = {
    "precise_drift": (
        "Deliberate slow float; no bounce or spring; "
        "transforms are purposeful and arrive cleanly."
    ),
    "slow_drift": (
        "Very slow ambient motion; elements breathe; "
        "no fast snaps; transitions feel like tide not traffic."
    ),
    "gentle_spring": (
        "Soft follow; slight spring on pointer interaction; "
        "warmth in easing; nothing feels mechanical."
    ),
    "reactive_field": (
        "Event-driven; elements respond physically to pointer / scroll; "
        "physics-adjacent; energy visible."
    ),
    "immediate": (
        "No decorative easing; transforms are instant or very short; "
        "clinical precision over expressiveness."
    ),
    "slow_dissolve": (
        "Opacity-forward transitions; elements appear by dissolving in; "
        "motion is atmospheric not mechanical."
    ),
}

_DEFAULT_MOTION_LANGUAGE = "slow_drift"


def _pick_motion_language(tone_keywords: list[str]) -> tuple[str, str]:
    """Return (motion_language_id, description) from tone keywords."""
    for kw in tone_keywords:
        ml = _MOTION_LANGUAGE_MAP.get(kw.lower().strip())
        if ml:
            return ml, _MOTION_LANGUAGE_DESCRIPTIONS[ml]
    return _DEFAULT_MOTION_LANGUAGE, _MOTION_LANGUAGE_DESCRIPTIONS[_DEFAULT_MOTION_LANGUAGE]


# ---------------------------------------------------------------------------
# Material / light mapping
# ---------------------------------------------------------------------------

_MATERIAL_RULES: list[tuple[frozenset[str], str, str]] = [
    # (aesthetic_keywords, material_hint, description)
    (
        frozenset({"dark", "noir", "cinematic", "moody", "shadows"}),
        "volumetric_fog",
        "Dark field; emissive/glowing geometry; minimal ambient; directional point lights.",
    ),
    (
        frozenset({"clean", "minimal", "white", "airy", "light"}),
        "soft_diffuse",
        "High-key diffuse; flat or area lights; matte surfaces; low contrast shadow.",
    ),
    (
        frozenset({"editorial", "typographic", "print", "grid"}),
        "type_dominant",
        "Geometry serves as substrate for type; materials are neutral; type carries visual weight.",
    ),
    (
        frozenset({"textured", "raw", "film", "grain", "analog"}),
        "grain_surface",
        "Surface roughness; film-grain overlay hint; materials feel physical not digital.",
    ),
    (
        frozenset({"architectural", "structured", "geometric", "precise"}),
        "geometric_precision",
        "Hard-edge geometry; clean normals; metallic or ceramic materials; sharp shadows.",
    ),
    (
        frozenset({"warm", "amber", "earthy", "organic", "wood"}),
        "warm_ambient",
        "Warm-toned ambient; incandescent-like point lights; surfaces have warmth.",
    ),
    (
        frozenset({"neon", "vibrant", "electric", "glitch", "digital"}),
        "emissive_glow",
        "Emissive bright geometry on dark field; color bleed; bloom hint.",
    ),
]

_DEFAULT_MATERIAL_HINT = "soft_diffuse"
_DEFAULT_MATERIAL_DESC = "Neutral diffuse materials; soft lighting; let shape carry meaning."


def _pick_material_hint(aesthetic_keywords: list[str]) -> tuple[str, str]:
    """Return (material_hint_id, description) from aesthetic keywords."""
    aset = {kw.lower().strip() for kw in aesthetic_keywords}
    for signals, hint, desc in _MATERIAL_RULES:
        if aset & signals:
            return hint, desc
    return _DEFAULT_MATERIAL_HINT, _DEFAULT_MATERIAL_DESC


# ---------------------------------------------------------------------------
# Primitive guidance: what 3D forms are identity-coherent
# ---------------------------------------------------------------------------

_PRIMITIVE_GUIDANCE_MAP: dict[str, str] = {
    "light_table": (
        "Use PlaneGeometry panels arranged like a contact sheet or lightbox. "
        "Images map to plane faces. Avoid torus knots or icosahedra unless justified."
    ),
    "darkroom": (
        "Use photo-frame-like quads emerging from black. "
        "Chemical-process feel: elements appear slowly with emissive trace edges."
    ),
    "studio_table": (
        "Use BoxGeometry, CylinderGeometry scaled as work objects — not decorative. "
        "Geometry represents actual tools/artefacts from the brief."
    ),
    "text_archive": (
        "Use TextGeometry or CSS3DRenderer for 3D text planes. "
        "No sphere/torus defaults. Space is the typographic container."
    ),
    "signal_field": (
        "Use BufferGeometry points/particles. "
        "Avoid mesh primitives; identity expressed as a field density distribution."
    ),
    "narrative_cinema": (
        "Use sequential depth-positioned planes or zones that the camera moves through. "
        "Each zone is a narrative beat, not a section card."
    ),
    "installation_field": (
        "Use low-poly sculptural geometry unique to the brief's content. "
        "Justify every object's presence in terms of identity or body of work."
    ),
    "grid_space": (
        "Use a modular BoxGeometry or InstancedMesh grid. "
        "Grid proportions derive from identity palette or layout logic."
    ),
    "object_theater": (
        "Use geometry that represents a real object from the person's work. "
        "E.g. a camera, a book, a tool — not an abstract icosahedron."
    ),
    "editorial_cosmos": (
        "Use sparse SphereGeometry points or floating planes at editorial scale. "
        "Vast negative space is intentional; avoid dense particle fields."
    ),
}

_DEFAULT_PRIMITIVE_GUIDANCE = (
    "Use geometry that can be justified by the identity brief. "
    "Torus knot and icosahedron are stock tutorial shapes — only use them if the "
    "brief's content/aesthetic specifically calls for that form. "
    "Prefer geometry that could be described as 'this shape because [identity reason]'."
)


def _pick_primitive_guidance(scene_metaphor: str) -> str:
    return _PRIMITIVE_GUIDANCE_MAP.get(scene_metaphor, _DEFAULT_PRIMITIVE_GUIDANCE)


# ---------------------------------------------------------------------------
# Scene grammar result
# ---------------------------------------------------------------------------


@dataclass
class SceneGrammar:
    """Identity-derived creative grammar for the 3D/interactive generator."""

    scene_metaphor: str
    scene_metaphor_description: str
    motion_language: str
    motion_language_description: str
    material_hint: str
    material_hint_description: str
    primitive_guidance: str
    rationale: dict[str, str] = field(default_factory=dict)

    def to_creative_direction(self) -> dict[str, Any]:
        """Compact creative direction dict for injection into execution contract / creative_brief."""
        return {
            "scene_metaphor": self.scene_metaphor,
            "scene_metaphor_description": self.scene_metaphor_description,
            "motion_language": self.motion_language,
            "motion_language_description": self.motion_language_description,
            "material_hint": self.material_hint,
            "material_hint_description": self.material_hint_description,
            "primitive_guidance": self.primitive_guidance,
            "scene_rationale": self.rationale,
        }


def build_scene_grammar_from_identity(
    identity_brief: dict[str, Any] | None,
    structured_identity: dict[str, Any] | None,
) -> SceneGrammar:
    """
    Derive a concrete scene grammar from identity signals.

    Reads tone_keywords, aesthetic_keywords, content_types, themes from
    identity_brief and structured_identity.  Returns a SceneGrammar that
    the generator can use directly to justify scene metaphor, motion behavior,
    material choices, and primitive selection.
    """
    ib = identity_brief if isinstance(identity_brief, dict) else {}
    si = structured_identity if isinstance(structured_identity, dict) else {}

    # Collect signals from both sources
    tone_kw: list[str] = list(ib.get("tone_keywords") or []) or list(si.get("tone") or [])
    aesthetic_kw: list[str] = list(ib.get("aesthetic_keywords") or []) or list(si.get("aesthetic") or [])
    content_types_raw: list[str] = list(si.get("content_types") or []) or list(ib.get("content_types") or [])
    themes_raw: list[str] = list(si.get("themes") or [])

    content_types = {c.lower().strip() for c in content_types_raw}
    themes = {t.lower().strip() for t in themes_raw}

    scene_metaphor, scene_desc = _pick_scene_metaphor(content_types, themes)
    motion_lang, motion_desc = _pick_motion_language(tone_kw)
    material_hint, material_desc = _pick_material_hint(aesthetic_kw)
    primitive_guidance = _pick_primitive_guidance(scene_metaphor)

    rationale: dict[str, str] = {}
    if tone_kw:
        rationale["motion_from"] = f"tone_keywords: {tone_kw[:3]}"
    if aesthetic_kw:
        rationale["material_from"] = f"aesthetic_keywords: {aesthetic_kw[:3]}"
    if themes:
        rationale["metaphor_from"] = f"themes: {sorted(themes)[:3]}"
    if content_types:
        rationale["metaphor_content_from"] = f"content_types: {sorted(content_types)[:3]}"

    return SceneGrammar(
        scene_metaphor=scene_metaphor,
        scene_metaphor_description=scene_desc,
        motion_language=motion_lang,
        motion_language_description=motion_desc,
        material_hint=material_hint,
        material_hint_description=material_desc,
        primitive_guidance=primitive_guidance,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Scene topology / section grammar for non-portfolio interactive lanes
# ---------------------------------------------------------------------------

#: Valid non-portfolio scene topologies for interactive/WebGL builds.
INTERACTIVE_SCENE_TOPOLOGIES: tuple[str, ...] = (
    "immersive_stage",
    "spatial_vignette_system",
    "narrative_zones",
    "layered_world",
    "constellation",
    "archive_field",
    "signal_field",
    "editorial_cosmos",
    "studio_table",
    "memory_map",
    "object_theater",
    "light_table",
    "installation_field",
)

#: Portfolio-structured section names — used to detect portfolio-shell regression.
PORTFOLIO_SHELL_SECTIONS: frozenset[str] = frozenset(
    {
        "hero",
        "projects",
        "projects_grid",
        "work",
        "selected_work",
        "about",
        "contact",
        "timeline",
        "recognitions",
        "services",
        "testimonials",
        "footer",
    }
)

#: Stock Three.js tutorial geometry patterns — flagged as identity-ungrounded.
GENERIC_THREEJS_DEMO_PATTERNS: frozenset[str] = frozenset(
    {
        "torusknot",
        "torus_knot",
        "TorusKnotGeometry",
        "IcosahedronGeometry",
        "icosahedron",
        "OctahedronGeometry",
        "octahedron",
        "orbit_around",
        "OrbitControls",
        "AxesHelper",
        "GridHelper",
        "wireframe demo",
        "spinning cube",
    }
)


__all__ = [
    "GENERIC_THREEJS_DEMO_PATTERNS",
    "INTERACTIVE_SCENE_TOPOLOGIES",
    "PORTFOLIO_SHELL_SECTIONS",
    "SceneGrammar",
    "build_scene_grammar_from_identity",
]
