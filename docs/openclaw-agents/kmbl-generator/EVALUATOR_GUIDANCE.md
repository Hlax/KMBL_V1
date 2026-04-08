# EVALUATOR_GUIDANCE.md — Passing evaluation with immersive experiences

**Read when:** `cool_generation_lane_active` or `execution_contract.lane` contains immersive/spatial lanes.

This document clarifies what **evaluator-passing immersive experiences** look like. The first run failing suggests the evaluator was flagging "portfolio-shell-as-default" behavior. The second run passed because it reduced **portfolio narrative language** and emphasized **interactive spatial design**. This guide formalizes that distinction.

## Key Evaluator Signals

### ❌ Portfolio-Shell Antipattern (fails evaluation)
- Landing page with hero + "Work" + "About" + "Contact" sections in sequence
- Copy-heavy introductions ("I'm a creative producer who...")
- Project grid with project cards and descriptions
- Conventional folder hierarchy (hero/projects/about)

**Why it fails:** Boring HTML template masquerading as interactive experience. The evaluator flags this as **portfolio_shell_used: true** in scene manifest.

### ✅ Immersive Spatial Design Pattern (passes evaluation)
- **One committed scene topology** (e.g., `light_table`, `editorial_cosmos`, `constellation`)
- **Interactivity as navigation**, not decoration (pointer moves/reveals, scroll triggers scene changes, not scroll-decor)
- **Identity made visible spatially**: "warm playful identity" → light colors, gentle spring motion; "bold industrial identity" → hard edges, precise grid
- **No hero/projects/about** unless the scene structure itself is *the* organization (e.g., constellation nodes = projects, but organized by metaphor, not folder)
- **Typography as part of the scene**, not overlaid
- **Minimal explanatory text** — let the space speak

## Evaluation Metrics

### Evaluation Checklist (what passes)

**Spatial Commitment (hard rule)**
- [✓] Scene uses ONE consistent topology from GEOMETRY.md section
- [✓] Scene manifest correctly names that topology
- [✓] Composition rules are enforced (e.g., "no stacked sections" for light_table)
- [✓] Layout strategy (`depth_sequence`, `scatter_field`, `editorial_sparse`) is evident in HTML structure

**Identity Grounding (hard rule)**
- [✓] At least **one** identity signal is **visually present** (`color`, `motion`, `geometry`, `tone`)
- [✓] `kmbl_scene_manifest_v1.identity_signals_used` is honest (not inflated)
- [✓] Color palette matches `identity_brief.palette_hex`
- [✓] Motion pacing matches `identity_brief.motion_tone` (e.g., "gentle spring" appears in GSAP easing)

**Interactivity Integration (hard rule)**
- [✓] Scene responds to pointer/scroll **with spatial meaning**, not just animation
- [✓] Interaction rules from `execution_contract.geometry_system.interaction_rules` are present
- [✓] Reduced-motion fallback exists (verified in CSS or JS)
- [✓] No decorative orbit camera; interaction must reveal or navigate

**Frontend Excellence (soft rule, but weighted)**
- [✓] HTML is clean, modular, single-file or multi-file with resolved asset paths
- [✓] Three.js scene initializes; canvas renders correctly
- [✓] No console errors; no 404s for local assets
- [✓] GSAP animations respect timing and easing from manifest

**Anti-Portfolio Language (soft but important)**
- [✓] No "About Me" + project card grid combo
- [✓] No hero section with "I'm a [role]" copy
- [✓] No conventional contact form or "Services" list
- [✓] Copy is sparse, declarative ("Studio Table. Work Objects. Scattered. Illuminated.") not narrative

### Evaluation Failure Modes

**Fails if:**
1. **Portfolio shell + 3D decoration** — hero with hero/projects/about sections, then a rotating canvas element. Evaluator flags: "Canvas stacking is not immersive."
2. **Scene manifest is false** — claims `scene_topology: "constellation"` but HTML is grid of project cards. Evaluator flags: "Manifest does not match implementation."
3. **Interaction is cosmetic** — OrbitControls is enabled but viewer can only rotate; scene structure doesn't change. Evaluator flags: "Interaction reveals nothing; decoration only."
4. **Identity signals are generic** — purple + blue gradient + minimal copy. Evaluator flags: "No grounding to specific identity brief."
5. **Token exhaustion** — multipage attempt bloats to unsustainable size mid-generation. Evaluator flags: "Context overflow; cannot validate."

## Strategy Adjustments for Success

### Rule 1: Choose ONE topology and commit

Do not mix portfolio shell + immersive canvas. Pick **one**:
- **Portfolio-adjacent only if:** `scene_topology: "editorial_cosmos"` with sparse text nodes as layout, not sections.
- **Immersive only if:** canvas/spatial structure is the entire surface, no traditional sections.

### Rule 2: Make identity visible, not verbose

**Bad:**
```html
<p>My creative practice blends motion and spatial thinking...</p>
```

**Good:**
```html
<div data-kmbl-scene="editorial_cosmos" data-kmbl-motion="slow_drift">
  <!-- Scene topology speaks for identity -->
  <canvas id="stage"></canvas>
  <!-- Spare text as spatial elements -->
</div>
```

### Rule 3: Design for evaluation

Emit `kmbl_scene_manifest_v1` **always** when geometry_system is present:
- Evaluator **will** check scene manifest against HTML structure.
- If manifest says "constellation" but HTML is grid, evaluator fails the run.
- `portfolio_shell_used: false` is a trust marker.

### Rule 4: Limit scope early

If `build_spec.steps` includes 5+ sections:
- Either **choose one** as a spatial centerpiece + sparse references to others (e.g., "constellation nodes for projects, two narrative zones").
- Or **use `habitat_manifest_v2`** to batch across runs (primary experience in run N, additional zones in runs N+1, N+2).
- Do not attempt all in one run and fail on token budget.

## Practical Checklist Before Emitting

```
BEFORE sending artifact_outputs:

[ ] Scene manifest emitted (if geometry_system present)
[ ] Scene topology matches HTML structure
[ ] Identity_signals_used is ≤3 signals (not inflated)
[ ] Interaction rules from contract are visible (reduced-motion, pointer, scroll)
[ ] Copy is sparse (<50 words outside of sparse text nodes)
[ ] No "About Me", "Services", or "Contact Form" copy patterns unless they are spatial nodes
[ ] color_mapping_rules from geometry_system are reflected in CSS
[ ] motion_mapping_rules from geometry_system are in GSAP easing
[ ] Canvas/scene initializes without errors (test before shipping)
[ ] File paths in artifact_outputs match actual files on disk
```

## Examples of Passing Topologies

### Example: editorial_cosmos (sparse, vast, moody)

```json
{
  "scene_topology": "editorial_cosmos",
  "primitive_set": ["TextGeometry", "PlaneGeometry"],
  "composition_rules": [
    "Vast negative space is structural",
    "Elements spaced at perceptual intervals",
    "Type is geometry; no decorative objects"
  ],
  "motion_mapping_rules": ["slow_drift", "precise_drift on interaction"],
  "identity_signals_used": ["moody", "minimal", "noir"]
}
```

**Passes if:** The HTML renders sparse text nodes in 3D space, uses GSAP for gentle drift, no hero/project grid.

### Example: light_table (photography, archival)

```json
{
  "scene_topology": "light_table",
  "primitive_set": ["PlaneGeometry", "Light"],
  "composition_rules": [
    "Image planes illuminated from behind",
    "No stacked sections",
    "Parallax depth organizes content"
  ],
  "interaction_rules": ["Pointer drives parallax", "Reduced-motion fallback"],
  "library_stack": ["three", "gsap"],
  "identity_signals_used": ["photography", "cinematic"]
}
```

**Passes if:** Images are planes in 3D space, lighting is intentional, pointer interaction parallax hints at depth, no conventional hero text.

### Example: constellation (relational, emergent)

```json
{
  "scene_topology": "constellation",
  "primitive_set": ["SphereGeometry"],
  "composition_rules": [
    "Nodes distributed in 3D space",
    "Relationships emerge on interaction",
    "Edges optional (only if relationships are structural)"
  ],
  "interaction_rules": ["Proximity clustering on hover", "Reduced-motion fallback"],
  "density_profile": "sparse_editorial",
  "identity_signals_used": ["networked", "relational", "minimal"]
}
```

**Passes if:** Nodes (spheres, boxes) are scattered in space, hover reveals relationships, no grid or folder layout.

## When Multi-Page is Necessary

If `build_spec.steps` mandates >1 page or `execution_contract.habitat_strategy` is multi-zone:

### Option A: Multi-zone within single page (preferred unless token-limited)
- Scene has 2–3 distinct zones accessible by scroll or button.
- Each zone is a mini-scene with its own topology.
- Return **one** `artifact_outputs` with single HTML.
- Scene manifest lists all zones: `"zones": ["hero_zone", "project_zone", "contact_zone"]`.

### Option B: Multi-run habitat (when Option A is too large)
- Run 1: Primary immersive experience (e.g., constellation of projects).
- Run 2: Secondary zone (e.g., process/about as editorial_cosmos).
- Run 3: Tertiary (contact as installation_field).
- Return `habitat_manifest_v2` pointing to artifact IDs/threads.
- Evaluator checks that zones cohere (same palette, motion language, identity grounding).

### Option C: Portfolio fallback only if cool_lane is false
- If `cool_generation_lane_active` is **false**, standard portfolio is acceptable.
- If **true**, immersive topology is **required** for passing evaluation.

## Key Takeaway

**Evaluation passes when you commit to **one scene topology** and make identity **spatially visible** through composition, motion, and interaction — not through verbose copy.** The Harvey Lacsina run passed because it chose `editorial_cosmos` (sparse, vast, moody), used Three.js meaningfully (portrait geometry), and kept copy minimal.
