# GEOMETRY.md — kmbl-generator scene composition reference

Read when `kmbl_execution_contract.geometry_system` is present or `experience_mode` is `immersive_identity_experience` / `immersive_spatial_portfolio`. Hard rules in **SOUL.md**. Library stack in **LIBRARIES.md**.

## Geometry contract fields

`kmbl_execution_contract.geometry_system` contains:

| Field | What it means |
|---|---|
| `mode` | Which rendering technology to use (`three`/`svg`/`pixi`/`diagram`/`babylon`/`css_spatial`/`hybrid_three_svg`) |
| `primitive_set` | Identity-justified geometry forms — use these, not defaults |
| `composition_rules` | Spatial layout rules derived from identity tone/themes |
| `layout_strategy` | High-level composition pattern (`depth_sequence`/`scatter_field`/`editorial_sparse`/`structured_grid`/`graph_layout`/`scene_composition`) |
| `motion_mapping_rules` | Tone-derived motion behavior (use for all transitions/animations) |
| `color_mapping_rules` | Aesthetic-derived material/light guidance |
| `interaction_rules` | How viewer presence affects scene (required: reduced-motion fallback) |
| `typography_spatial_role` | How type relates to geometry (`text_as_geometry`/`type_dominant`/`overlay_on_scene`) |
| `density_profile` | `sparse_editorial` / `dense_field` / `single_focus` |
| `scene_topology` | Which non-portfolio surface archetype applies (see below) |
| `derivation_signals` | Which identity signals drove these choices (for traceability) |

## Non-portfolio scene topologies

For `immersive_identity_experience` and `immersive_spatial_portfolio`, organize the surface as one of these — **not** as hero/projects/about/contact:

| Topology | Character |
|---|---|
| `immersive_stage` | Subject-forward; theatrical light; identity IS the scene |
| `spatial_vignette_system` | Series of spatial moments at different depths |
| `narrative_zones` | Camera moves through distinct conceptual zones |
| `layered_world` | Parallax depth layers that reveal with scroll/pointer |
| `constellation` | Small nodes in space; relationships emerge on interaction |
| `archive_field` | Dense grid or scatter of work artifacts; browsable spatially |
| `signal_field` | Particle/point cloud; identity as distributed presence |
| `editorial_cosmos` | Sparse spaced elements; vast negative space as weight |
| `studio_table` | Work objects scattered on surface; maker's table aesthetic |
| `memory_map` | Spatial map of past/places/works; orthographic or near-top-down |
| `object_theater` | Key objects isolated with theatrical light; no background clutter |
| `light_table` | Image panels illuminated from behind; photography / archival feel |
| `installation_field` | Viewer inside the space; objects respond to presence |

## Composition principles by layout_strategy

**`depth_sequence`** (narrative_cinema, layered_world)
- Camera traverses depth, not user scrolls a page
- Each zone is a beat; pacing is temporal
- No section headers — transitions carry the narrative

**`scatter_field`** (signal_field, constellation, installation_field)
- Elements distributed in 3D space by algorithm or identity data
- Proximity and density carry meaning
- Interaction reveals detail, not navigation to sections

**`editorial_sparse`** (editorial_cosmos, text_archive)
- Vast negative space is structural, not empty
- Few elements; each carries proportional weight
- Type is geometry; no decorative flourish

**`structured_grid`** (grid_space, archive_field, light_table)
- Grid proportions derived from identity or golden ratio, not Bootstrap
- Tension breaks at identity-significant positions
- Hover/focus isolates items without leaving the grid

**`graph_layout`** (diagram mode)
- Nodes represent entities from identity / body of work
- Force-directed or hierarchical layout driven by relationships
- D3 simulation; do not fake graph with static SVG

## Primitive selection discipline

Every geometry form must pass this test: **"I used [shape] because [identity reason]."**

Bad: "I used TorusKnotGeometry because it's geometric."
Good: "I used InstancedMesh planes because the brief shows photography and this creates a contact-sheet spatial arrangement."

When `primitive_set` is provided in `geometry_system`, use those. When it's absent:
- Match the form to `scene_topology` from the table in this doc
- Avoid tutorial shapes (torus knot, icosahedron) as defaults
- Prefer: planes (image work), points/particles (signal/dispersal), boxes (objects/artifacts), lines (relationships/networks), text geometry (editorial)

## Motion discipline

Use `motion_mapping_rules` from `geometry_system` for all animation:
- `slow_drift` → easing: "power1.inOut", duration 1.5–3s, no bounce
- `precise_drift` → easing: "power2.out", arrives cleanly, no overshoot
- `gentle_spring` → gsap elasticOut or physics spring; warmth, not snappiness
- `reactive_field` → requestAnimationFrame loop, pointer-velocity aware
- `immediate` → no easing; zero or 0.1s transitions only
- `slow_dissolve` → opacity transitions 0.8–2s; translate minimal; atmospheric

## Reduced-motion requirement

Always include:
```css
@media (prefers-reduced-motion: reduce) {
  /* disable all decorative animation */
  * { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
```
Or use `matchMedia("(prefers-reduced-motion: reduce)")` to disable RAF loop.
This is **not optional** — it is in `interaction_rules`.

## Identity grounding markers

Embed at least one marker so the evaluator can verify grounding:

```html
<!-- kmbl-scene-metaphor: light_table -->
<!-- kmbl-motion-language: slow_drift -->
```
Or as data attribute on root scene element:
```html
<div data-kmbl-scene="light_table" data-kmbl-motion="slow_drift">
```

These are SECONDARY hints; the primary grounding evidence is `kmbl_scene_manifest_v1`.

## Scene manifest emission

Always emit when `geometry_system` is present (cool lane):

```json
{
  "kmbl_scene_manifest_v1": {
    "scene_metaphor": "light_table",
    "geometry_mode": "three",
    "scene_topology": "light_table",
    "primitive_set": ["PlaneGeometry", "TextureLoader", "AmbientLight"],
    "composition_rules": [
      "No stacked sections",
      "Image planes arranged at depth",
      "Viewer navigates by pointer parallax"
    ],
    "interaction_rules": ["Pointer drives parallax", "Reduced-motion fallback present"],
    "library_stack": ["three", "gsap"],
    "identity_signals_used": ["photography", "cinematic", "dark", "moody"],
    "scene_fingerprint": "",
    "portfolio_shell_used": false,
    "claimed_delta_from_prior": "Changed from editorial_cosmos to light_table; added TextureLoader panel system; motion changed from precise_drift to slow_drift"
  }
}
```

`claimed_delta_from_prior` is optional but helps the evaluator track iteration intent.
