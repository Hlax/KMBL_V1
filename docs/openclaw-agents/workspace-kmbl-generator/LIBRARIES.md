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
- **Multiple geometry_modes in one run:** Do not mix `three`, `svg`, `pixi`, and `babylon` in one artifact. Pick one and commit.
- **Asset bottlenecks:** Do not embed large texture maps inline; use CDN or relative paths under `component/assets/`. Keep base64 data URIs under 50KB.
- **Unused library bloat:** If you only need `three` + `gsap` for a scene, do not load `postprocessing`, `troika-three-text`, and `camera-controls` speculatively.

## Practical library selection guide

### When to use Three.js (default)
- Identity involves **spatial, 3D, or immersive** themes
- Scene topology is `constellation`, `editorial_cosmos`, `light_table`, `immersive_stage`, `layered_world`, or similar
- Interaction is **pointer-driven parallax**, **scroll-linked depth**, or **object-centric** rotation
- Best for: hero subjects, abstract geometry, spatial navigation, 3D text

**Example identity signals triggering Three.js:**
- "minimalist 3D aesthetic"
- "interactive spatial portfolio"
- "cinematic depth"
- "particle/constellation networking"

**Approximate bundle size:** ~200KB gzipped (includes animation helpers)

---

### When to use SVG (svg.js or raw SVG)
- Identity is **2D, illustrative, or graphic-first**
- Scene topology is `diagram` or `interactive_network` or flat/poster-like
- Content is **shapes, paths, text vectors** (no photographic elements)
- Interaction is **draw/animate strokes**, **node/link manipulation**, or **interactive infographic**
- Best for: brand marks, network graphs, data viz, illustrative layouts

**Example identity signals triggering SVG:**
- "graphic design, not spatial"
- "vector illustration heavy"
- "systems/network visualization"
- "hand-drawn or geometric mark"

**When to choose svg.js:** Dynamic SVG generation (e.g., growing paths, DOM-heavy animation).
**When to use raw SVG:** Static or CSS-animated content (simpler, smaller footprint).

**Approximate bundle size:** ~50KB (if using svg.js); raw SVG is zero overhead.

---

### When to use D3 (diagram mode)
- Identity involves **data relationships, networks, hierarchies, or graph structures**
- Scene topology is `graph_layout` or `network_field`
- Interaction is **zoom/pan**, **node highlight**, **force simulation**, or **hierarchy navigation**
- Best for: org charts, dependency graphs, knowledge maps, relational diagrams

**Example identity signals triggering D3:**
- "networked / distributed"
- "systems thinking"
- "knowledge mapping"
- "force-directed relationships"

**Modular import pattern (lightweight):**
```javascript
import * as d3 from 'https://cdn.jsdelivr.net/npm/d3@7/+esm';
// or pick individual modules
import { forceSimulation, forceLink } from 'https://cdn.jsdelivr.net/npm/d3-force@3/+esm';
```

**Approximate bundle size:** ~100–200KB depending on submodules; ESM + tree-shake reduces overhead.

---

### When to use PixiJS (pixi mode)
- Identity is **2D canvas animation, sprite-heavy, or frame-based-motion**
- Scene topology is `motion_field` or **2D-first** design
- Interaction is **particle effects**, **sprite pooling**, **high-frame-rate animation**,or **game-like motion**
- Best for: motion branding, sprite atlases, real-time particle systems, playful 2D experiences

**Example identity signals triggering PixiJS:**
- "playful, energetic 2D animation"
- "sprite-driven or frame-animation"
- "high-performance particle field"
- "arcade / game aesthetic"

**Approximate bundle size:** ~200KB gzipped (includes renderer, stage, sprites).

---

### When to use Babylon.js (babylon mode)
- Identity is **advanced 3D: physics, game engine behavior, or complex rendering**
- Brief explicitly requires **rigid body physics**, **collision detection**, or **game loop**
- Scene topology is `object_theater` with **physics-driven interactions**
- Interaction is **throwing objects**, **gravity simulation**, or **physics-based animation**
- Best for: product showcases with physics, VR-like experiences, complex mechanical scenes

**Example identity signals triggering Babylon:**
- "physics-driven interaction"
- "game-like or kinetic experience"
- "complex 3D mechanics"
- Only if brief **explicitly** calls for physics (do not default to Babylon)

**Note:** Bundle is larger (~800K–1.2MB); use only when truly necessary.

**Approximate bundle size:** ~800KB–1.2MB gzipped (full engine); use tree-shaking or trimmed build if possible.

---

### When to use Gaussian Splat (escalation, rare)
- **Only when `execution_contract.escalation_lane == "gaussian_splat_v1"`**
- Identity is based on **captured / scanned 3D** (photogrammetry, NeRF, real-world scanning)
- Brief explicitly calls for **"captured 3D reality"** or **"scanned environment"**
- Do **not** use for generic 3D or default immersive experiences

**Library:** `https://github.com/antimatter15/gaussian-splats-3d` (Three-compatible wrapper)

**Asset pipeline:** `.splat` or `.ply` files under `component/assets/`

**Bundle overhead:** Splat assets vary; typical splat: 10–50MB (delivered externally, not embedded)

**Example identity signals (rare):** 
- "photographic 3D reality"
- "scanned environment or monument"
- Only if captured assets are provided or plan-signed

---

### When to use Hybrid (Three.js + SVG)
- Primary experience is **3D scene**, but **UI/annotations are 2D**
- Example: 3D object with SVG labels, or 3D scene with 2D overlay controls
- Interaction: **pointer drives 3D; overlay updates 2D annotations**

**Pattern:**
```html
<div style="position: relative;">
  <canvas id="three-stage"></canvas>
  <svg id="annotations"></svg> <!-- positioned absolutely, screen-space -->
</div>
```

**Use when:** 3D scene needs dynamic 2D labels, callouts, or UI that stays fixed on screen while 3D rotates.

**Avoid:** Mixing two full-featured 3D renderers (e.g., Three.js + Babylon side-by-side) — choose one.

---

## Library CDN links (recommended)

| Library | CDN | Version | Bundle size |
|---------|-----|---------|---|
| Three.js | `https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js` | 0.160.0 | ~200KB |
| GSAP | `https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js` | 3.12.5 | ~40KB |
| D3 (full) | `https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js` | 7.x | ~200KB |
| D3 (modular) | `https://cdn.jsdelivr.net/npm/d3@7/+esm` | 7.x | varies (~50-100KB per module) |
| SVG.js | `https://cdn.jsdelivr.net/npm/svg.js@3/dist/svg.min.js` | 3.x | ~50KB |
| PixiJS | `https://cdn.jsdelivr.net/npm/pixi.js@7/dist/pixi.min.js` | 7.x | ~200KB |
| Babylon.js | `https://cdn.babylonjs.com/babylon.js` | Nightly or stable | ~800KB–1.2MB |
| Gaussian Splats 3D | `https://cdn.jsdelivr.net/npm/gaussian-splats-3d@0.7.1/build/index.js` | 0.7.1 | ~50KB + asset overhead |

---

## Scene manifest library_stack field

Always declare the actual library stack in scene manifest:

```json
{
  "library_stack": ["three", "gsap"],
  "optional_libraries": []
}
```

or

```json
{
  "library_stack": ["d3"],
  "optional_libraries": ["jointjs"]
}
```

Evaluator uses this to verify **no undeclared escalations** (e.g., if manifest says `three` only, but response loads Babylon, evaluator flags).

---

## Token-aware library strategy

If approach token budget constraints:

1. **Minimize library count:** One primary + one animation (e.g., `three` + `gsap`, not `three` + `gsap` + `postprocessing` + `troika`).
2. **Use CDN always:** Zero overhead for serving from CDN. Local bundling requires npm/build overhead.
3. **Avoid image-heavy assets:** Textures, splat files, photographic planes all add bulk to artifact size + load time. Prefer procedural geometry or stylized visuals.
4. **Defer optional escalations:** If unclear whether `troika-three-text` or `postprocessing` is necessary, start without. Add only if manifest justifies.
5. **Batch multi-lib experiences:** If brief requires both 3D (`three`) and data viz (`d3`), split across multi-run habitat (primary: 3D, secondary: diagram).

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
