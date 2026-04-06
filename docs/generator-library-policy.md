# KMBL Frontend Generation Library & Lane Policy

## Goal
Keep the generator lightweight, reliable, and visually ambitious without exploding stack complexity.

The generator should master one primary interactive frontend path and use other graphics libraries only as controlled escalation lanes.

---

## Primary default lane

### Default stack
- HTML
- CSS
- JavaScript
- Three.js
- GSAP

### Default use cases
Use this lane for most interactive visual builds, including:
- identity-driven landing pages
- animated hero sections
- motion-forward portfolios
- light 3D scenes
- camera motion
- particle systems
- shader-enhanced backgrounds
- scroll-reactive experiences
- immersive but lightweight web experiences

### Reason
This is the main KMBL generation lane because it provides the best balance of:
- expressiveness
- low runtime complexity
- strong browser support
- no framework requirement
- easy local preview assembly
- compatibility with static or lightweight app-style outputs

---

## Allowed shader file types

The generator may emit:
- `.glsl`
- `.vert`
- `.frag`
- `.wgsl`

These should be used only when they materially improve the visual result.

---

## Escalation lanes

### Lane: WebGPU / WGSL
Allowed when the planner explicitly asks for:
- advanced GPU effects
- shader-first visuals
- compute-like rendering behavior
- modern GPU pipeline experiments
- visuals that are clearly better served by WGSL/WebGPU than standard WebGL

#### Preferred stack
- HTML
- CSS
- JavaScript
- Three.js WebGPU path
- WGSL

#### Rules
- Do not choose WGSL/WebGPU by default.
- Prefer Three.js-based WebGPU usage over raw low-level WebGPU unless the brief is explicitly shader-first.
- Must include a graceful fallback or clear degradation path when practical.

---

### Lane: Minimal shader-first WebGL
Allowed only when the brief is explicitly shader-first, experimental, or minimalist.

#### Allowed libraries
- OGL
- TWGL
- regl

#### Rules
- Do not use these as the default 3D lane.
- Use only when the build is primarily about custom rendering, shader experimentation, or minimal abstraction.
- Prefer OGL for very lightweight custom scenes.
- Prefer TWGL or regl only when the generation clearly benefits from lower-level rendering control.

---

### Lane: 2D GPU canvas
Allowed when the experience is fundamentally 2D and does not need spatial 3D.

#### Allowed libraries
- PixiJS

#### Use cases
- interactive 2D scenes
- motion graphics
- animated UI canvases
- stylized 2D experiences
- game-like 2D interfaces

#### Rules
- Do not use PixiJS for true 3D scenes.
- Prefer PixiJS only when the brief is clearly 2D-first.

---

### Lane: Gaussian Splat / captured 3D

**Not a default lane.** Specialist escalation for real-world captured 3D, photoreal navigable scenes, and spatial showcases driven by splat data — not generic abstract motion sites.

#### Allowed when the brief explicitly benefits from
- photoreal navigable captured scenes
- real-world object or space viewing
- immersive identity moments based on scanned or captured content
- splat-based visual storytelling where ordinary Three.js meshes would be the wrong abstraction

#### Avoid when
- the site is generic marketing, typography, or CSS motion — use the default Three.js + GSAP lane
- standard geometry, materials, and shaders suffice
- no splat or point-cloud assets are available or planned
- the goal is lightweight hero animation without captured 3D

#### Preferred stack (KMBL standard)
- HTML, CSS, JavaScript
- **Three.js** as the scene backbone
- **`gaussian-splats-3d`** (Three-compatible Gaussian splat viewer; load via CDN alongside Three)
- **GSAP** for UI motion around the splat view (optional but common)

**Alternates (documented only, not equal defaults):** heavier WebGPU-only splat viewers (e.g. some Spark-based stacks) — use only if the brief demands them; prefer the Three-compatible path for local preview and single-bundle fits.

#### Planner / contract
- Set `execution_contract.escalation_lane` to `gaussian_splat_v1` when selecting this lane.
- Include `gaussian-splats-3d` in `allowed_libraries` and justify in the build spec / creative brief.
- Do **not** select this lane for “cool 3D” alone without captured/scanned content intent.

#### Generator
- Keep one HTML entry, CDN-loaded Three + splat viewer, assets under `component/…`.
- **Data:** `.splat`, `.ply` (and common compressed variants if the chosen loader supports them) — place under `component/assets/` or similar; document loading and fallbacks.
- **Fallback:** if assets are missing or too large, show an explicit message and a static poster or simplified Three scene — never fail silently.

---

## Not default lanes

These may be supported later, but should not be default generation targets unless explicitly requested or architecturally necessary:
- React Three Fiber
- Babylon.js
- A-Frame
- PlayCanvas
- Spline export workflows
- Needle Engine

### Reason
These add stack complexity, workflow overhead, or framework coupling that is unnecessary for KMBL’s current goal:
cool, lightweight, identity-driven frontend experiences that run locally and assemble cleanly.

---

## Lane selection rules

### Choose the default lane when:
- the brief asks for interactive visual design
- the identity suggests motion, depth, atmosphere, or premium polish
- a lightweight 3D or faux-3D experience is sufficient
- no framework is required
- the result should assemble into simple local preview output

### Choose WGSL/WebGPU only when:
- the planner explicitly requests advanced GPU/shader behavior
- the visual concept materially depends on modern GPU rendering
- standard Three.js WebGL would likely underdeliver the intended effect

### Choose OGL/TWGL/regl only when:
- the experience is shader-first
- minimal abstraction is part of the goal
- the scene is custom-rendering-centric rather than app-centric

### Choose PixiJS only when:
- the experience is truly 2D
- performance-heavy 2D rendering is needed
- spatial 3D is not the point

---

## Generator output expectations

The generator should prefer:
- one HTML entrypoint
- organized CSS and JS files
- optional shader files
- CDN-loaded libraries when appropriate
- no heavy build tooling unless explicitly required
- outputs that can be ingested into workspace and previewed locally

The generator should avoid:
- unnecessary frameworks
- unnecessary package/build complexity
- choosing exotic rendering stacks without clear brief justification
- using multiple rendering libraries in one build unless explicitly justified

---

## Allowed library guidance

### Preferred defaults
- `three`
- `gsap`

### Optional support libraries
- `lil-gui`
- `camera-controls`
- `postprocessing`
- `troika-three-text`
- `gl-matrix`
- `glslify`

### Controlled escalation libraries
- `pixi`
- `ogl`
- `twgl`
- `regl`

### Conditional advanced path
- `wgsl` / WebGPU-oriented rendering through Three.js when explicitly justified

### Gaussian Splat (specialist — with `escalation_lane: gaussian_splat_v1`)
- `gaussian-splats-3d` (Three-compatible; primary KMBL choice)

### Asset file types (interactive / splat)
- Shaders: `.glsl`, `.vert`, `.frag`, `.wgsl`
- Splat / point data: `.splat`, `.ply` (binary or text PLY per loader)

---

## Planning and contract guidance

Planner should:
- choose the simplest lane that can still achieve the intended visual ambition
- prefer the default Three.js + GSAP lane for most interactive work
- explicitly justify any escalation lane in the build spec
- avoid selecting advanced graphics stacks just because they are available

Generator should:
- follow the chosen lane faithfully
- keep implementation lightweight
- use shader files only when visually beneficial
- preserve local previewability and workspace assembly compatibility
