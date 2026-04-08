# COOL_LANE_STRATEGY.md — Mastering cool_generation_lane and multi-experience batching

**Read when:** `cool_generation_lane_active` is true, or build_spec requires complex multi-zone/multi-page experiences.

This document bridges the evaluation constraints documented in EVALUATOR_GUIDANCE.md with practical strategies for tackling ambitious identity experiences without token overflow.

## What is cool_generation_lane?

**cool_generation_lane** is a signal that the orchestrator is **routing this run through an advanced execution mode**. When active:

- **Geometry system is present** (not default three + gsap).
- **Scene manifest emission is mandatory** (`kmbl_scene_manifest_v1` must be in JSON response).
- **Evaluation is stricter** — evaluator checks that artifact matches manifest and identity is grounded spatially.
- **Library escalation is permitted** — you may use Babylon, Gaussian splat, WGSL/WebGPU if manifest justifies it.
- **Multi-zone / multi-page strategies are expected** — if build_spec is large, batching across runs is acceptable and preferred.

## Core Principle

**Choose scope, commit to execution, emit scene manifest.**

If you cannot ship a complete, working artifact within token budget:
1. **Reduce scope** (one scene topology; fewer sections).
2. **Use multi-run batching** (primary experience in run N, secondary in N+1).
3. **Fail cleanly** with `contract_failure` only if neither is feasible.

---

## Single-Run Strategy (when experience fits one page)

### Rule 1: Pick ONE scene topology

From GEOMETRY.md or REFERENCE_PATTERNS.md:
- `immersive_stage` — hero/subject-forward
- `spatial_vignette_system` — multi-moment depth sequence
- `narrative_zones` — camera moves through conceptual spaces
- `layered_world` — parallax depth layers
- `constellation` — nodes in space, relationships emerge
- `archive_field` — dense grid/scatter browsable spatially
- `signal_field` — particle/point cloud
- `editorial_cosmos` — sparse spaced elements
- `studio_table` — work objects on surface
- `memory_map` — spatial map of past/places
- `object_theater` — key objects isolated, theatrical light
- `light_table` — image panels illuminated
- `installation_field` — viewer inside space; objects respond

**DO NOT MIX** multiple topologies in one run (e.g., "constellation + hero + editorial_cosmos"). Mixing muddles the manifest and confuses evaluation.

### Rule 2: Structure the experience under that topology

If build_spec.steps lists Hero / Work / About / Contact:
- **Option A (editorial_cosmos / light_table):** Make each section a sparse node or plane in the scene. No folder hierarchy.
- **Option B (constellation):** Map Work to constellation nodes, Hero to a central node, Contact to a sparse instruction node. All navigable through scene, not sections.
- **Option C (narrative_zones / sequential depth):** Camera journey through zones; each zone is a thematic moment (Hero zone → Work zone → About zone → Contact zone). Scroll or button triggers transitions.

### Rule 3: Emit scene manifest accurately

```json
{
  "kmbl_scene_manifest_v1": {
    "scene_metaphor": "editorial_cosmos",
    "geometry_mode": "three",
    "scene_topology": "editorial_cosmos",
    "primitive_set": ["TextGeometry", "PlaneGeometry"],
    "composition_rules": [
      "Vast negative space is structural",
      "Few elements; each carries weight",
      "Type is geometry; no overlay"
    ],
    "interaction_rules": [
      "Pointer position affects parallax",
      "Scroll reveals (optional, if scroll_trigger in payload)",
      "Reduced-motion fallback present"
    ],
    "library_stack": ["three", "gsap"],
    "identity_signals_used": ["minimal", "moody", "noir"],
    "portfolio_shell_used": false,
    "claimed_delta_from_prior": null
  }
}
```

**Evaluator will check:**
1. Scene topology name matches HTML structure.
2. Primitive set is evident in the code (THREE.ObjectType).
3. Composition rules are enforced (e.g., "no folder hierarchy" → HTML has no `<section id="projects">` grid).
4. Identity signals are visible (colors, motion, geometry).
5. `portfolio_shell_used: false` is true.

---

## Multi-Zone (Single Page) Strategy

**Use when:** Multiple sections / build_spec.steps fit into one page under a unified topology.

### Pattern: Zone Activation + Scroll Trigger

```html
<!DOCTYPE html>
<html>
<head>
  <style>
    body { margin: 0; height: 300vh; } /* allow scroll */
    .zone { 
      position: fixed; 
      top: 0; 
      left: 0; 
      width: 100%; 
      height: 100vh; 
      display: none; 
    }
    .zone.active { display: block; }
  </style>
</head>
<body>
  <div id="zone-hero" class="zone active">
    <canvas id="canvas-hero"></canvas>
  </div>
  <div id="zone-work" class="zone">
    <canvas id="canvas-work"></canvas>
  </div>
  <div id="zone-contact" class="zone">
    <canvas id="canvas-contact"></canvas>
  </div>
  
  <script>
    const zones = {
      'zone-hero': { scene: null, active: false },
      'zone-work': { scene: null, active: false },
      'zone-contact': { scene: null, active: false }
    };
    
    window.addEventListener('scroll', () => {
      const vp = window.scrollY / window.innerHeight;
      
      if (vp < 1) { activateZone('zone-hero'); }
      else if (vp < 2) { activateZone('zone-work'); }
      else { activateZone('zone-contact'); }
    });
    
    function activateZone(zoneId) {
      Object.keys(zones).forEach(id => {
        const shouldActivate = id === zoneId;
        zones[id].active = shouldActivate;
        document.getElementById(id).classList.toggle('active', shouldActivate);
        
        if (shouldActivate && !zones[id].scene) {
          initZone(id);
        }
      });
    }
    
    function initZone(zoneId) {
      // Setup Three.js scene for this zone
      const canvas = document.getElementById('canvas-' + zoneId.split('-')[1]);
      if (!canvas) return;
      
      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
      const renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: true});
      renderer.setSize(window.innerWidth, window.innerHeight);
      
      // Zone-specific setup
      if (zoneId === 'zone-hero') {
        initHeroZone(scene, camera, renderer);
      } else if (zoneId === 'zone-work') {
        initWorkZone(scene, camera, renderer);
      } else if (zoneId === 'zone-contact') {
        initContactZone(scene, camera, renderer);
      }
      
      zones[zoneId].scene = {scene, camera, renderer};
    }
    
    function initHeroZone(scene, camera, renderer) {
      // Hero zone: protagonist-forward geometry
      const geom = new THREE.SphereGeometry(1, 32, 32);
      const mat = new THREE.MeshStandardMaterial({color: 0x7a00df});
      const mesh = new THREE.Mesh(geom, mat);
      scene.add(mesh);
      
      function animate() {
        if (!zones['zone-hero'].active) return;
        mesh.rotation.x += 0.001;
        mesh.rotation.y += 0.002;
        renderer.render(scene, camera);
        requestAnimationFrame(animate);
      }
      animate();
    }
    
    // Similar for initWorkZone, initContactZone...
  </script>
</body>
</html>
```

**Scene manifest for multi-zone:**
```json
{
  "kmbl_scene_manifest_v1": {
    "scene_topology": "narrative_zones",
    "zones": [
      {
        "id": "hero",
        "topology": "immersive_stage",
        "content_summary": "Protagonist-forward identity intro"
      },
      {
        "id": "work",
        "topology": "constellation",
        "content_summary": "Project nodes, relational"
      },
      {
        "id": "contact",
        "topology": "editorial_cosmos",
        "content_summary": "Sparse contact cues"
      }
    ],
    "portfolio_shell_used": false
  }
}
```

---

## Multi-Run Habitat Strategy (when one page is too large)

**Use when:**
- `build_spec.steps` has 5+ sections
- Scene complexity exceeds safe token budget (experience_mode is `immersive_identity_experience`, not `static_frontend`))
- `execution_contract.habitat_strategy` is `multi_zone_durable` or similar

### Approach: Batch across 2–3 runs

**Run 1: Primary immersive experience**
- Scope: Hero + Work (constellation)
- Deliverable: 1 HTML, complete and previewable
- Scene manifest: indicates primary artifact, hints at multi-run

```json
{
  "artifact_outputs": [{
    "role": "interactive_frontend_app_v1",
    "file_path": "component/preview/index.html",
    "content": "...constellation experience, hero + work..."
  }],
  "habitat_manifest_v2": {
    "version": 2,
    "artifact_id": "run_1_primary",
    "is_primary": true,
    "sequence_order": 1,
    "zones": [
      {"id": "hero", "topology": "immersive_stage", "entry_point": "index.html#hero"},
      {"id": "work", "topology": "constellation", "entry_point": "index.html#work"}
    ],
    "next_artifact_id": "run_2_secondary",
    "entry_html": "component/preview/index.html"
  },
  "kmbl_scene_manifest_v1": {
    "scene_topology": "narrative_zones",
    "portfolio_shell_used": false,
    "habitat_primary": true,
    "habitat_expected_zones": ["hero", "work", "process", "contact"]
  }
}
```

**Run 2: Secondary zone (Process / About)**
- Scope: Process narrative (editorial_cosmos)
- Deliverable: Self-contained HTML, but linked from Run 1
- Manifest: references Run 1 as parent

```json
{
  "artifact_outputs": [{
    "role": "interactive_frontend_app_v1",
    "file_path": "component/preview/index.html",
    "content": "...editorial_cosmos process narrative..."
  }],
  "habitat_manifest_v2": {
    "version": 2,
    "artifact_id": "run_2_secondary",
    "parent_artifact_id": "run_1_primary",
    "sequence_order": 2,
    "zones": [
      {"id": "process", "topology": "editorial_cosmos", "entry_point": "index.html"}
    ],
    "prev_artifact_id": "run_1_primary",
    "next_artifact_id": "run_3_tertiary"
  }
}
```

**Run 3: Tertiary zone (Contact / Coda)**
- Scope: Contact / closing (sparse UI, small)
- Manifest: part of sequence

```json
{
  "artifact_outputs": [{
    "role": "interactive_frontend_app_v1",
    "file_path": "component/preview/index.html",
    "content": "...installation_field or sparse contact..."
  }],
  "habitat_manifest_v2": {
    "version": 2,
    "artifact_id": "run_3_tertiary",
    "parent_artifact_id": "run_1_primary",
    "sequence_order": 3,
    "zones": [
      {"id": "contact", "topology": "installation_field", "entry_point": "index.html"}
    ],
    "prev_artifact_id": "run_2_secondary"
  }
}
```

**Evaluator logic:**
1. Checks primary artifact + habitat manifest for coherence.
2. Verifies each zone has a distinct, justified scene topology.
3. Ensures color/motion/identity signals are consistent across zones.
4. Accepts multi-run if primary artifact is complete and previewable.

---

## Token Budget Planning

| Strategy | Typical tokens | When to use |
|---|---|---|
| **Single-run, single topology** | 2–3K | Simple identity, one scene, <3 sections |
| **Single-run, multi-zone** | 4–6K | Complex identity, 3–4 sections unified by one flow |
| **Multi-run, 2–3 runs** | 6–10K total | Very complex identity, 5+ sections, each deserves own topology |

**Token estimation:**
- Scene setup + Three.js initialization: ~500 tokens
- One complete zone (geometry, lighting, animation): ~1–1.5K tokens
- Scene manifest + JSON wrapper: ~200 tokens
- Multi-zone orchestration JS: +500 tokens per zone

**If approaching budget:**
1. Reduce primitive complexity (one light instead of three, simpler geometry).
2. Use CDN libraries (no bundling overhead).
3. Batch into multi-run (primary + secondary).

---

## Preventing Evaluation Rejection

### Checklist Before Emitting

**Manifest & Structure**
- [ ] Scene manifest emitted (`kmbl_scene_manifest_v1` present)
- [ ] Scene topology matches HTML structure (e.g., if manifest says "constellation", HTML has node scatter, not grid)
- [ ] `portfolio_shell_used: false` (not hero/projects/about sections)

**Identity Grounding**
- [ ] At least one identity signal visible in code (color, motion, geometry)
- [ ] Identity signals in manifest match actual code
- [ ] Palette colors from `identity_brief.palette_hex` (not generic purple/blue)

**Interaction**
- [ ] Pointer or scroll interaction is present
- [ ] Reduced-motion fallback exists (CSS `@media` + JS check)
- [ ] No decorative OrbitControls unless explicitly called for

**Technical**
- [ ] Canvas renders without errors
- [ ] No 404s for local assets (`component/…` paths)
- [ ] Fonts/textures load from CDN (not local files under workspace)
- [ ] Scene initializes on page load

**Multi-Zone (if applicable)**
- [ ] Zone activation logic is correct (scroll triggers, button nav, etc.)
- [ ] Each zone has distinct canvas/scene
- [ ] Zone transition is smooth (no flicker)

**Multi-Run (if applicable)**
- [ ] Primary artifact is complete and previewable
- [ ] `habitat_manifest_v2` references are correct
- [ ] Zones have consistent identity signals across runs

### Common Rejection Patterns

❌ **Manifest vs. Code Mismatch**
- Manifest: `"scene_topology": "constellation"`
- HTML: `<div class="projects"><div class="project-card">...</div></div>` (grid, not nodes)
- **Fix:** Change manifest to `"editorial_sparse"` if using grid, or restructure HTML as constellation.

❌ **Portfolio shell hidden in topology**
- Manifest: `"portfolio_shell_used": false`
- HTML: Hero section + Work section + About section + Contact footer
- **Fix:** Either (1) set `portfolio_shell_used: true` and own the shell, or (2) restructure as true spatial experience.

❌ **Token overflow mid-run**
- Start generating multi-zone; exceed context budget halfway
- Return partial artifact + error
- **Fix:** Fail early with `contract_failure: {code: "context_overflow", recoverable: true}` and suggest multi-run habitat.

---

## Examples

### Example 1: Single Topology, Single Zone (edits existing LIBRARIES.md pattern)

**Brief:** Minimal, moody, editorial identity; no multi-section requirement.

**Strategy:** One `editorial_cosmos` scene.

**Tokens:** ~2.5K (scene + manifest).

**Manifest:**
```json
{
  "scene_topology": "editorial_cosmos",
  "primitive_set": ["TextGeometry"],
  "portfolio_shell_used": false,
  "identity_signals_used": ["minimal", "noir"]
}
```

**Code sketch:**
```javascript
// Text nodes in 3D space, slow drift motion
// No sections, no grid → pure spatial
```

---

### Example 2: Single Page, Multi-Zone (one HTML, scroll-driven behavior)

**Brief:** Complex identity requiring "work + process + contact" but evaluator strict.

**Strategy:** Single HTML, three zones activated by scroll position.

**Tokens:** ~5K (orchestration + 3 zones).

**Manifest:**
```json
{
  "scene_topology": "narrative_zones",
  "zones": [
    {"id": "work", "topology": "constellation"},
    {"id": "process", "topology": "editorial_cosmos"},
    {"id": "contact", "topology": "installation_field"}
  ],
  "portfolio_shell_used": false
}
```

**Code sketch:**
```javascript
// Three fixed-position zones; scroll switches active zone
// Each zone has own Three.js scene/canvas
```

---

### Example 3: Multi-Run Habitat (complex, batched)

**Brief:** Ambitious identity requiring 5+ sections; one page exceeds token budget.

**Strategy:** Run 1 (primary: hero + constellation work), Run 2 (secondary: process), Run 3 (tertiary: contact).

**Tokens:** ~8K total (primary ~3.5K, secondary ~2.5K, tertiary ~2K).

**Manifest (Run 1):**
```json
{
  "is_primary": true,
  "zones": [
    {"id": "hero", "topology": "immersive_stage"},
    {"id": "work", "topology": "constellation"}
  ],
  "portfolio_shell_used": false,
  "habitat_primary": true
}
```

**Manifests (Run 2, 3):** Reference Run 1 as parent; define secondary zones.

---

## Recap: Decision Tree

```
1. Is cool_generation_lane_active?
   No → Use standard static_frontend_file_v1 (portfolio OK)
   
2. Yes. How many sections?
   <3 → Single topology, single zone (1 run, 2–3K tokens)
   3–4 → Single topology, multi-zone (1 run, 4–6K tokens)
   5+ → Multi-run habitat (2–3 runs, 6–10K tokens)

3. Pick scene topology from GEOMETRY.md / REFERENCE_PATTERNS.md

4. Implement in HTML + emit kmbl_scene_manifest_v1

5. Check evaluation checklist (earlier in this doc)

6. Ship artifact_outputs + manifest
   OR contract_failure if infeasible
```

---

## References

- EVALUATOR_GUIDANCE.md — Evaluation rules and pass/fail signals
- REFERENCE_PATTERNS.md — Working code examples per topology
- GEOMETRY.md — Scene topologies and composition rules
- LIBRARIES.md — Library stack policy
