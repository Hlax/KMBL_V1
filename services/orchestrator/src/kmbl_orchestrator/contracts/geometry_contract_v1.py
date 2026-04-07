"""
Geometry Contract V1 — typed contract defining how a build's 3D/visual system is composed.

Derived from identity signals + planner intent + experience_mode.
Surfaced in execution_contract.geometry_system and generator payloads so geometry choices
are explicit rules, not inferred from vague scene adjectives.

The contract covers:
  - geometry_mode: rendering technology (three/svg/pixi/diagram/babylon/css_spatial)
  - primitive_set: justified geometry forms for this identity
  - composition_rules: spatial layout + anti-portfolio rules
  - motion_mapping_rules: tone → motion behavior
  - color_mapping_rules: aesthetic → material/light choices
  - interaction_rules: how viewer presence affects the scene
  - scene_topology: which non-portfolio surface type applies
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Geometry mode vocabulary
# ---------------------------------------------------------------------------

GeometryMode = Literal[
    "three",           # Three.js mesh/geometry (default interactive 3D)
    "svg",             # SVG-first spatial/editorial (SVG.js or raw inline SVG)
    "pixi",            # PixiJS 2D canvas (2D-first motion/sprite work)
    "diagram",         # Data-viz / graph / relationship (D3 or JointJS)
    "babylon",         # Babylon.js — physics/engine (explicit escalation only)
    "css_spatial",     # CSS 3D transforms + GSAP (no canvas; pure HTML/CSS spatial)
    "hybrid_three_svg" # Three.js scene + SVG vector overlay (text/type as geometry layer)
]

GEOMETRY_MODES: frozenset[str] = frozenset(
    {"three", "svg", "pixi", "diagram", "babylon", "css_spatial", "hybrid_three_svg"}
)

# ---------------------------------------------------------------------------
# Primitive sets keyed by scene_topology
# ---------------------------------------------------------------------------

_PRIMITIVE_SET_BY_TOPOLOGY: dict[str, list[str]] = {
    "light_table": ["PlaneGeometry", "MeshBasicMaterial", "TextureLoader", "AmbientLight"],
    "darkroom": ["PlaneGeometry", "MeshStandardMaterial", "SpotLight", "FogExp2"],
    "studio_table": ["BoxGeometry", "CylinderGeometry", "MeshPhysicalMaterial", "DirectionalLight"],
    "signal_field": ["BufferGeometry", "Points", "ShaderMaterial", "PointLight"],
    "narrative_cinema": ["PlaneGeometry", "Group", "PerspectiveCamera", "FogExp2"],
    "installation_field": ["Group", "custom_geometry", "AmbientLight", "PointLight"],
    "grid_space": ["InstancedMesh", "BoxGeometry", "MeshStandardMaterial"],
    "object_theater": ["Group", "custom_mesh", "SpotLight", "ShadowMap"],
    "editorial_cosmos": ["SphereGeometry", "Points", "LineSegments", "AmbientLight"],
    "text_archive": ["BufferGeometry", "Points", "CSS3DRenderer"],
    "constellation": ["SphereGeometry", "LineSegments", "BufferGeometry"],
    "memory_map": ["PlaneGeometry", "Group", "OrthographicCamera"],
    "archive_field": ["InstancedMesh", "PlaneGeometry", "AmbientLight"],
    "spatial_vignette_system": ["Group", "PlaneGeometry", "FogExp2", "AmbientLight"],
    "immersive_stage": ["Group", "custom_geometry", "DirectionalLight", "PointLight"],
    "layered_world": ["Group", "PlaneGeometry", "AmbientLight", "FogExp2"],
}

_DEFAULT_PRIMITIVES = ["Group", "MeshStandardMaterial", "AmbientLight", "DirectionalLight"]

# ---------------------------------------------------------------------------
# Composition rules by theme/complexity/experience_mode
# ---------------------------------------------------------------------------

_BASE_COMPOSITION_ANTI_PORTFOLIO = (
    "Do not produce stacked hero/projects/about/contact section structure"
)

_COMPOSITION_BY_THEME: dict[str, list[str]] = {
    "experimental": [
        "Asymmetric or non-grid composition",
        "Non-card primitives — geometry reflects identity not tutorial",
        "Viewer position and pointer affect scene state",
    ],
    "cinematic": [
        "Sequential depth zones — camera traverses not user scrolls",
        "Temporal composition: reveal has rhythm and intention",
        "Depth and parallax over lateral layout",
    ],
    "editorial": [
        "Structured grid with deliberate tension breaks",
        "Vast negative space is intentional weight",
        "Typography carries spatial role not just label function",
    ],
    "artistic": [
        "Composition derived from body of work not template grid",
        "Material and light choices mirror aesthetic tone",
        "Scene tells identity story spatially",
    ],
    "spatial": [
        "Scene is spatial environment — viewer is inside not scrolling past",
        "Depth layering replaces section stacking",
        "Camera or pointer movement reveals rather than scrolling",
    ],
}

# ---------------------------------------------------------------------------
# Motion mapping rules by tone keyword
# ---------------------------------------------------------------------------

_MOTION_RULES_BY_TONE: dict[str, list[str]] = {
    "restrained": [
        "Slow drift; no bounce; transforms complete fully before next begins",
        "Precise arrival: elements land deliberately, no overshoot",
    ],
    "controlled": [
        "Measured pacing; purposeful not decorative",
        "State changes are instantaneous or short; no flourish",
    ],
    "warm": [
        "Soft spring on pointer interaction; nothing feels mechanical",
        "Follow-through on motion; warmth in easing curves",
    ],
    "organic": [
        "Physics-adjacent; energy dissipates naturally",
        "No linear transitions; motion has breath",
    ],
    "experimental": [
        "Physics-adjacent; energy responds to pointer events",
        "Frame-rate-aware; stutter is acceptable if intentional",
        "Non-linear easing; unexpected motion is feature not bug",
    ],
    "kinetic": [
        "Energy always present; elements breathe constantly",
        "Interaction amplifies existing motion; viewer participates",
    ],
    "minimal": [
        "No decorative easing; immediate or very short transitions",
        "Motion budget minimal — move only what needs to move",
    ],
    "clinical": [
        "Snap transitions; no easing drift",
        "Information changes are instant; motion is structural only",
    ],
    "cinematic": [
        "Slow reveal; camera-like motion; temporal composition",
        "Scene breathes between beats; nothing rushes",
    ],
    "bold": [
        "Arrives with weight; deliberate; no jitter",
        "Scale transitions over fade; presence not disappearance",
    ],
    "poetic": [
        "Dissolves and fades dominate over translate/scale",
        "Ambient motion in background; foreground is still",
    ],
    "dark": [
        "Slow ambient drift; shadows move with weight",
        "Reveal from dark — elements emerge, not appear",
    ],
}

_DEFAULT_MOTION_RULES = [
    "Motion is purposeful; tied to identity tone not generic easing presets",
    "Avoid tutorial-style rotation/orbit as default animation behavior",
]

# ---------------------------------------------------------------------------
# Color / material mapping by aesthetic keywords
# ---------------------------------------------------------------------------

_COLOR_RULES_BY_AESTHETIC: dict[str, list[str]] = {
    "dark": ["Use identity_brief.palette_hex or dark field (#0a0a0a base)", "Emissive/glowing geometry on dark bg"],
    "noir": ["High contrast; deep blacks; accent light only", "Materials absorb light; minimal ambient"],
    "minimal": ["White or near-white bg; flat materials; geometry carries weight not color"],
    "clean": ["Neutral palette; soft shadows; no saturated accent unless identity_brief says so"],
    "warm": ["Warm-toned ambient; incandescent-like directional light; ochre or amber tones"],
    "cinematic": ["LUT-style color grading hint in CSS overlay; deep tones; high contrast"],
    "neon": ["Emissive bright geometry; dark bg; bloom hint in post-processing"],
    "editorial": ["Typography-forward; colors support text not compete; neutral geometry"],
    "textured": ["Roughness on surfaces; grain overlay hint; materials feel physical"],
    "monochrome": ["Single-hue with value variation; depth from tone not color"],
}

_DEFAULT_COLOR_RULES = [
    "Derive palette from identity_brief.palette_hex when present",
    "Avoid generic purple/teal gradients unless identity palette supports them",
]

# ---------------------------------------------------------------------------
# Geometry mode selection
# ---------------------------------------------------------------------------

_NETWORK_THEMES = frozenset({"network", "systems", "data", "graph", "connective", "technical", "mapping"})
_PHYSICS_THEMES = frozenset({"physics", "simulation", "game", "engine", "interactive_physics"})
_EDITORIAL_AESTHETICS = frozenset({"editorial", "typographic", "print", "text_heavy"})
_2D_AESTHETICS = frozenset({"2d", "sprite", "pixel", "flat", "motion_graphics"})


def _select_geometry_mode(
    content_types: set[str],
    themes: set[str],
    experience_mode: str,
    complexity: str,
    aesthetic_kw: set[str],
    scene_topology: str | None,
) -> str:
    """Select geometry mode from identity + experience signals."""
    # Network/systems/graph/data → diagram lane
    if themes & _NETWORK_THEMES or content_types & {"data", "information", "graph", "network"}:
        return "diagram"

    # 2D-first motion/sprite → PixiJS
    if aesthetic_kw & _2D_AESTHETICS:
        return "pixi"

    # Physics/engine/game (explicit) → Babylon escalation
    if themes & _PHYSICS_THEMES:
        return "babylon"

    # Signal field → Three.js (particles are its native territory)
    if scene_topology in ("signal_field", "constellation", "installation_field"):
        return "three"

    # Typography-dominant editorial, low complexity → css_spatial or hybrid
    if aesthetic_kw & _EDITORIAL_AESTHETICS:
        if content_types <= {"writing"} and content_types:
            return "css_spatial" if complexity == "simple" else "hybrid_three_svg"
        if complexity in ("simple", "moderate") and not (themes & {"cinematic", "experimental"}):
            return "hybrid_three_svg"

    # Writing-only without strong visual signal → SVG editorial
    if content_types <= {"writing"} and content_types and not themes & {"cinematic", "experimental"}:
        return "svg"

    # Default: Three.js
    return "three"


# ---------------------------------------------------------------------------
# Contract derivation
# ---------------------------------------------------------------------------


def derive_geometry_contract(
    identity_brief: dict[str, Any] | None,
    structured_identity: dict[str, Any] | None,
    build_spec: dict[str, Any] | None,
) -> "GeometryContractV1":
    """
    Derive a GeometryContractV1 from identity + planner signals.

    Reads:
    - identity_brief: tone_keywords, aesthetic_keywords, image_refs
    - structured_identity: themes, visual_tendencies, content_types, complexity
    - build_spec: experience_mode, site_archetype, creative_brief.scene_metaphor/scene_topology

    Returns a compact typed contract for injection into execution_contract.geometry_system.
    """
    ib = identity_brief if isinstance(identity_brief, dict) else {}
    si = structured_identity if isinstance(structured_identity, dict) else {}
    bs = build_spec if isinstance(build_spec, dict) else {}
    cb = bs.get("creative_brief") if isinstance(bs.get("creative_brief"), dict) else {}

    tone_kw: list[str] = list(ib.get("tone_keywords") or []) or list(si.get("tone") or [])
    aesthetic_kw: list[str] = list(ib.get("aesthetic_keywords") or [])
    content_types = {c.lower().strip() for c in (si.get("content_types") or [])}
    themes = {t.lower().strip() for t in (si.get("themes") or [])}
    complexity: str = str(si.get("complexity") or "moderate").lower().strip()
    experience_mode: str = str(bs.get("experience_mode") or "").lower().strip()
    aesthetic_set = {a.lower().strip() for a in aesthetic_kw}

    # Prefer planner-specified scene_topology from creative_brief
    scene_topology: str | None = (
        cb.get("scene_metaphor") or cb.get("scene_topology") or None
    )

    geometry_mode = _select_geometry_mode(
        content_types, themes, experience_mode, complexity, aesthetic_set, scene_topology,
    )

    # Primitive set: from topology first, else geometry mode defaults
    if scene_topology and scene_topology in _PRIMITIVE_SET_BY_TOPOLOGY:
        primitive_set = list(_PRIMITIVE_SET_BY_TOPOLOGY[scene_topology])
    elif geometry_mode == "svg":
        primitive_set = ["SVGElement", "path", "text", "circle", "linearGradient"]
    elif geometry_mode == "pixi":
        primitive_set = ["PIXI.Sprite", "PIXI.Graphics", "PIXI.Container", "PIXI.Filter"]
    elif geometry_mode == "diagram":
        primitive_set = ["node", "link", "cluster", "force_simulation", "edge_label"]
    elif geometry_mode == "babylon":
        primitive_set = ["MeshBuilder", "PhysicsImpostor", "ArcRotateCamera", "HemisphericLight"]
    elif geometry_mode == "css_spatial":
        primitive_set = ["perspective_container", "transform_plane", "transition_reveal"]
    elif geometry_mode == "hybrid_three_svg":
        primitive_set = ["PlaneGeometry", "CSS3DRenderer", "SVGElement", "TextureLoader"]
    else:
        primitive_set = list(_DEFAULT_PRIMITIVES)

    # Composition rules: base anti-portfolio + theme-specific
    composition_rules = [_BASE_COMPOSITION_ANTI_PORTFOLIO]
    for theme in ("experimental", "cinematic", "editorial", "artistic", "spatial"):
        if theme in themes:
            composition_rules.extend(_COMPOSITION_BY_THEME.get(theme, []))
            break
    if experience_mode in ("immersive_identity_experience", "immersive_spatial_portfolio"):
        composition_rules.append("Scene is spatial environment — viewer inside not scrolling past")
    if complexity == "ambitious":
        composition_rules.append("Use depth and layering over flat stacking")
    composition_rules = list(dict.fromkeys(composition_rules))[:8]  # dedupe, cap

    # Motion rules: first matching tone keyword wins; accumulate up to 2 rules
    motion_rules: list[str] = []
    for kw in tone_kw:
        rules = _MOTION_RULES_BY_TONE.get(kw.lower().strip())
        if rules:
            motion_rules.extend(rules)
            if len(motion_rules) >= 2:
                break
    if not motion_rules:
        motion_rules = list(_DEFAULT_MOTION_RULES)
    motion_rules = motion_rules[:4]

    # Color / material rules: first matching aesthetic keyword
    color_rules: list[str] = []
    for ak in aesthetic_kw:
        rules = _COLOR_RULES_BY_AESTHETIC.get(ak.lower().strip())
        if rules:
            color_rules.extend(rules)
            if len(color_rules) >= 2:
                break
    if not color_rules:
        color_rules = list(_DEFAULT_COLOR_RULES)
    color_rules = color_rules[:4]

    # Interaction rules
    interaction_rules = ["Reduced-motion fallback required (prefers-reduced-motion media query)"]
    if geometry_mode == "three":
        interaction_rules.append(
            "Pointer/scroll affects scene state — not just decorative background canvas"
        )
    if experience_mode in ("immersive_identity_experience", "immersive_spatial_portfolio"):
        interaction_rules.append("Primary interaction is spatial navigation not button/card clicking")

    # Layout strategy
    if scene_topology in ("narrative_cinema", "layered_world"):
        layout_strategy = "depth_sequence"
    elif scene_topology in ("signal_field", "constellation", "installation_field"):
        layout_strategy = "scatter_field"
    elif scene_topology in ("editorial_cosmos", "text_archive"):
        layout_strategy = "editorial_sparse"
    elif scene_topology in ("grid_space", "archive_field"):
        layout_strategy = "structured_grid"
    elif geometry_mode == "diagram":
        layout_strategy = "graph_layout"
    else:
        layout_strategy = "scene_composition"

    # Typography spatial role
    if geometry_mode in ("hybrid_three_svg", "css_spatial"):
        typography_spatial_role = "text_as_geometry"
    elif aesthetic_set & {"editorial", "typographic", "print"}:
        typography_spatial_role = "type_dominant"
    else:
        typography_spatial_role = "overlay_on_scene"

    # Density profile
    if "restrained" in tone_kw or "minimal" in tone_kw or complexity == "simple":
        density_profile = "sparse_editorial"
    elif "experimental" in tone_kw or complexity == "ambitious":
        density_profile = "dense_field"
    else:
        density_profile = "single_focus"

    # Diagram relationship mode (only for diagram geometry)
    diagram_relationship_mode: str | None = None
    if geometry_mode == "diagram":
        if themes & {"network", "connective"}:
            diagram_relationship_mode = "force_directed_graph"
        elif themes & {"systems", "technical"}:
            diagram_relationship_mode = "hierarchical_tree"
        else:
            diagram_relationship_mode = "radial_cluster"

    # Derivation signals for traceability
    derivation_signals = [
        *(f"theme:{t}" for t in sorted(themes)[:3]),
        *(f"tone:{t}" for t in tone_kw[:2]),
        f"mode:{geometry_mode}",
        f"complexity:{complexity}",
    ]
    if scene_topology:
        derivation_signals.append(f"topology:{scene_topology}")

    return GeometryContractV1(
        mode=geometry_mode,
        primitive_set=primitive_set[:8],
        composition_rules=composition_rules,
        layout_strategy=layout_strategy,
        color_mapping_rules=color_rules,
        motion_mapping_rules=motion_rules,
        interaction_rules=interaction_rules[:4],
        typography_spatial_role=typography_spatial_role,
        density_profile=density_profile,
        scene_topology=scene_topology,
        diagram_relationship_mode=diagram_relationship_mode,
        derivation_signals=derivation_signals[:8],
    )


# ---------------------------------------------------------------------------
# Library recommendations per geometry mode
# ---------------------------------------------------------------------------

#: Primary library stack per geometry mode.
GEOMETRY_MODE_LIBRARY_MAP: dict[str, list[str]] = {
    "three": ["three", "gsap"],
    "svg": ["svg.js", "gsap"],
    "pixi": ["pixi"],
    "diagram": ["d3"],
    "babylon": ["babylon"],
    "css_spatial": ["gsap"],
    "hybrid_three_svg": ["three", "gsap"],
}

#: Optional additions that make sense per mode (planner may include selectively).
GEOMETRY_MODE_OPTIONAL_MAP: dict[str, list[str]] = {
    "three": ["troika-three-text", "camera-controls", "postprocessing"],
    "svg": ["gsap"],
    "pixi": ["gsap"],
    "diagram": ["jointjs"],
    "babylon": ["gsap"],
    "css_spatial": [],
    "hybrid_three_svg": ["troika-three-text"],
}


def geometry_mode_to_library_recommendations(mode: str) -> dict[str, Any]:
    """
    Return library recommendations for a given geometry mode.

    Used by planner to populate execution_contract.allowed_libraries.
    """
    primary = GEOMETRY_MODE_LIBRARY_MAP.get(mode, list(GEOMETRY_MODE_LIBRARY_MAP["three"]))
    optional = GEOMETRY_MODE_OPTIONAL_MAP.get(mode, [])
    return {
        "geometry_mode": mode,
        "primary_stack": primary,
        "optional_additions": optional,
        "anti_patterns": [
            "Do not use raw tutorial geometry (TorusKnotGeometry, IcosahedronGeometry) without justification",
            "Do not default to OrbitControls + spinning object as main interaction",
            "Do not overlay canvas on standard portfolio page and call it immersive",
        ],
    }


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------


class GeometryContractV1(BaseModel):
    """
    Machine-readable geometry composition contract.

    Compact enough for execution_contract.geometry_system and generator prompt summaries.
    """

    model_config = ConfigDict(extra="ignore")

    mode: str = "three"
    primitive_set: list[str] = Field(default_factory=list)
    composition_rules: list[str] = Field(default_factory=list)
    layout_strategy: str | None = None
    color_mapping_rules: list[str] = Field(default_factory=list)
    motion_mapping_rules: list[str] = Field(default_factory=list)
    interaction_rules: list[str] = Field(default_factory=list)
    typography_spatial_role: str | None = None
    density_profile: str | None = None
    scene_topology: str | None = None
    diagram_relationship_mode: str | None = None
    derivation_signals: list[str] = Field(default_factory=list)

    def to_compact_dict(self) -> dict[str, Any]:
        """Compact serialization for execution_contract / generator payload (excludes empty lists)."""
        d = self.model_dump(mode="python", exclude_none=True)
        # Remove empty list fields to save tokens
        return {k: v for k, v in d.items() if v not in ([], None, "")}


__all__ = [
    "GEOMETRY_MODES",
    "GEOMETRY_MODE_LIBRARY_MAP",
    "GEOMETRY_MODE_OPTIONAL_MAP",
    "GeometryContractV1",
    "GeometryMode",
    "derive_geometry_contract",
    "geometry_mode_to_library_recommendations",
]
