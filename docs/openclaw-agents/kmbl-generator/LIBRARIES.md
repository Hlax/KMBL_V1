# LIBRARIES.md — kmbl-generator library policy

Read when `kmbl_execution_contract.geometry_system` or `allowed_libraries` references a non-default stack. Hard rules in **SOUL.md**.

## Geometry-mode → primary library stack

| geometry_mode | Primary stack | Optional additions |
|---|---|---|
| `three` | `three`, `gsap` | `troika-three-text`, `camera-controls`, `postprocessing` |
| `svg` | `svg.js`, `gsap` | `paths.js` |
| `pixi` | `pixi` | `gsap` |
| `diagram` | `d3` | `jointjs` |
| `babylon` | `babylon` | `gsap` |
| `css_spatial` | `gsap` | — |
| `hybrid_three_svg` | `three`, `gsap` | `troika-three-text` |

Default when `geometry_system` absent: **`three` + `gsap`**.

## Library usage rules

**three / gsap (default)**
- Three.js via CDN (`unpkg.com/three@...` or `cdn.jsdelivr.net/npm/three`).
- `gsap` for timeline/scroll animations; `ScrollTrigger` plugin when scroll-linked.
- `troika-three-text` for high-quality in-scene text rendering (adds ~60KB).
- `camera-controls` only when orbit/pan/zoom is identity-justified, not default decoration.
- `postprocessing` only when bloom/chromatic aberration is explicitly called for in `creative_brief`.

**svg / svg.js**
- `svg.js` via CDN for SVG element creation and animation.
- For simple static SVG, use inline raw SVG in HTML — no library needed.
- `paths.js` only when generating complex parametric SVG paths programmatically.

**pixi**
- `pixi.js` via CDN for 2D canvas/sprite/motion-graphics work.
- Only when `geometry_mode == "pixi"` or brief is explicitly 2D-first.
- Do **not** use PixiJS as a substitute for Three.js 3D work.

**d3 / diagram**
- `d3` (modular: import only needed submodules via ESM CDN like `cdn.jsdelivr.net/npm/d3@7`).
- `jointjs` when the diagram needs interactive node/edge editing — not for read-only graphs.
- Use force-directed layout for network/connective briefs; hierarchical for systems/tree briefs.

**babylon (escalation)**
- Only when `execution_contract.geometry_system.mode == "babylon"` or brief needs physics/game engine.
- Import from `cdn.babylonjs.com/babylon.js`; keep scope tight.
- Do **not** default to Babylon for generic 3D — Three.js handles 99% of cases.

## Anti-patterns (hard — do not do these)

- **Tutorial geometry without justification:** `TorusKnotGeometry`, `IcosahedronGeometry`, `OctahedronGeometry` must be justified by the identity brief's content/aesthetic. If you cannot explain *why this form* in terms of identity, use a different primitive.
- **OrbitControls as main interaction:** camera orbit is decoration, not experience. Only include when brief explicitly calls for object inspection or navigable 3D space.
- **AxesHelper / GridHelper in output:** debug helpers. Remove before shipping.
- **Canvas overlay on standard portfolio page:** stacking a rotating 3D object above hero/projects/about/contact is not immersive. The scene IS the surface, or it is decoration — no middle ground.
- **React Three Fiber:** npm-build-required; preview pipeline does not support. Do not use.
- **Babylon for generic sites:** overkill; adds large bundle; use only for physics/engine-specific briefs.
- **Purple/teal gradient default:** only use if identity_brief.palette_hex supports it. Generic developer gradients are the palette equivalent of tutorial geometry.

## Scene manifest requirement (cool lane)

When `cool_generation_lane_active` and `geometry_system` is present, emit `kmbl_scene_manifest_v1` at top level:

```json
{
  "kmbl_scene_manifest_v1": {
    "scene_metaphor": "light_table",
    "geometry_mode": "three",
    "primitive_set": ["PlaneGeometry", "TextureLoader"],
    "composition_rules": ["No stacked sections", "Image planes in depth"],
    "interaction_rules": ["Pointer drives parallax"],
    "library_stack": ["three", "gsap"],
    "identity_signals_used": ["photography", "cinematic", "dark"],
    "lane_mix": {"primary_lane": "spatial_gallery", "secondary_lanes": ["editorial_story"]},
    "canvas_model": {"surface_type": "three", "zone_model": "multi_zone", "media_modes": ["image", "captioned"]},
    "media_transformation_summary": {"transformed_media_assets": 3},
    "source_transformation_summary": {"literal_reuse_hits": 0, "literal_reuse_detected": false},
    "identity_abstraction_summary": {"identity_to_scene_mapping": ["portrait->plane cluster"]},
    "scene_fingerprint": "",
    "portfolio_shell_used": false
  }
}
```

`scene_fingerprint` may be left empty — orchestrator computes it. `portfolio_shell_used: true` flags that you reverted to portfolio IA (evaluator will check).

## Mixed-lane strategy quick map

- `spatial_gallery + editorial_story`: scene-first surface plus one narrative module with explicit story cues.
- `hero_index + immersive_canvas`: indexed shell with one dominant canvas zone and bounded route hints.
- `index_atlas + editorial_story`: map/index navigation plus concise narrative annotations.

Do not claim mixed lanes only in prose. Reflect them in both artifact structure and `kmbl_scene_manifest_v1.lane_mix`.
