# REFERENCE_PATTERNS.md — Working examples for diverse immersive experiences

**Read when:** You need to understand how to execute different scene topologies, interact with multiple libraries, or structure multi-zone experiences. This complements LIBRARIES.md (policy) and GEOMETRY.md (composition rules) with **actual patterns** to copy/adapt.

## Quick Navigation

- **Three.js patterns**: Constellation, Editorial Cosmos, Light Table
- **SVG + D3 patterns**: Network diagrams, interactive graphs
- **Hybrid patterns**: Three.js + SVG overlay
- **Multi-zone patterns**: Sectioned immersive experiences
- **Multi-page patterns**: Habitat manifest strategies

---

## 1. Three.js Patterns

### 1.1 Constellation / Signal Field (sparse nodes, emergent relationships)

**Use when:** identity brief emphasizes "networked", "relational", "minimal", or "distributed presence".

**Key rules:**
- Nodes (spheres, boxes, points) in 3D space
- No grid; positions driven by algorithm or identity data
- Hover/click reveals relationships
- Dense field or sparse — tuned to brief

**Minimal working example structure:**

```javascript
// 1. Scene setup
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(60, w/h, 0.1, 10000);
const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});

// 2. Lighting: directional + ambient (identity-tuned)
const light1 = new THREE.DirectionalLight(0xffffff, 2);
const light2 = new THREE.PointLight(0xff00ff, 1.5, 100);
const ambience = new THREE.AmbientLight(0xffffff, 0.8);
scene.add(light1, light2, ambience);

// 3. Node cluster (identity data or algorithm-driven)
const nodes = [];
for (let i = 0; i < 12; i++) {
  const pos = getTupleFromIdentityOrPhysics(); // your distrib
  const geom = new THREE.SphereGeometry(0.5, 32, 32);
  const mat = new THREE.MeshStandardMaterial({
    color: identityPalette[i % identityPalette.length],
    roughness: 0.4,
    metalness: 0.1
  });
  const mesh = new THREE.Mesh(geom, mat);
  mesh.position.fromArray(pos);
  mesh.userData.id = i;
  nodes.push(mesh);
  scene.add(mesh);
}

// 4. Edges (optional; only if relationships are in identity)
// Use LineSegments or TubeGeometry for edges between related nodes

// 5. Pointer interaction (proximity clustering, hover reveal)
document.addEventListener('pointermove', (e) => {
  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2(
    (e.clientX / w) * 2 - 1,
    -(e.clientY / h) * 2 + 1
  );
  raycaster.setFromCamera(mouse, camera);
  const intersects = raycaster.intersectObjects(nodes);
  
  // Highlight hovered node + show edges
  nodes.forEach(n => n.scale.set(1, 1, 1));
  if (intersects.length > 0) {
    intersects[0].object.scale.set(1.3, 1.3, 1.3);
    // GSAP animate related nodes in/out
  }
});

// 6. Reduced-motion fallback
if (!matchMedia('(prefers-reduced-motion: reduce)').matches) {
  // animate loop
  requestAnimationFrame(animate);
} else {
  // static render
}
```

**Identity mapping:**
- Node count, distribution, colors → from `identity_brief.visual_signals`
- Lighting colors → from `identity_brief.palette_hex`
- Edges/connections → from `identity_brief.relationships` if present

---

### 1.2 Editorial Cosmos (vast, sparse, moody)

**Use when:** brief emphasizes "vast", "minimal", "noir", "editorial", "moody".

**Key rules:**
- Few elements; each carries proportional weight
- Vast negative space is structural, not empty
- Typography as geometry (TextGeometry or shader text)
- Motion is slow, deliberate (slow_drift, not reactive)

**Minimal working example:**

```javascript
// Sparse text nodes in 3D space
const textMeshes = [];
const texts = [
  { text: "Identity", pos: [-5, 2, -10] },
  { text: "Interactions", pos: [3, -1, -5] },
  { text: "Systems", pos: [0, 4, -15] }
];

const fontLoader = new THREE.FontLoader();
fontLoader.load('fonts/helvetiker_regular.typeface.json', (font) => {
  texts.forEach(({text, pos}) => {
    const geom = new THREE.TextGeometry(text, {
      font: font,
      size: 1.5,
      depth: 0.1,
      curveSegments: 12
    });
    const mat = new THREE.MeshStandardMaterial({
      color: 0xe5def7,
      emissive: 0x7a00df,
      emissiveIntensity: 0.15,
      roughness: 0.7
    });
    const mesh = new THREE.Mesh(geom, mat);
    mesh.position.fromArray(pos);
    scene.add(mesh);
    textMeshes.push(mesh);
  });
});

// Slow ambient rotation (slow_drift motion)
function animate() {
  textMeshes.forEach((mesh, i) => {
    mesh.rotation.z += 0.002;
    mesh.position.y += Math.sin(Date.now() * 0.0005 + i) * 0.01; // very slow bob
  });
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}
```

**Identity grounding:**
- Text content from `identity_brief.key_phrases` or `build_spec.steps` titles
- Colors from `palette_hex`
- Motion easing: `power1.inOut` for 1.5–3s cycles (slow_drift)

---

### 1.3 Light Table (photography / archival, planes in depth)

**Use when:** brief emphasizes "photography", "archival", "cinematic", "illuminated".

**Key rules:**
- Images as planes in 3D space
- Lighting is intentional (backlighting, sidelighting)
- No conventional grid; parallax depth organizes
- Hover/scroll parallax reveals

```javascript
// Create image planes
const imageUrls = [
  { url: 'img1.jpg', pos: [-8, 0, -5] },
  { url: 'img2.jpg', pos: [0, 3, -12] },
  { url: 'img3.jpg', pos: [5, -2, -18] }
];

const textureLoader = new THREE.TextureLoader();
const planes = [];

imageUrls.forEach(({url, pos}) => {
  const texture = textureLoader.load(url);
  const geom = new THREE.PlaneGeometry(4, 3); // aspect ratio
  const mat = new THREE.MeshStandardMaterial({
    map: texture,
    side: THREE.SingleSide,
    roughness: 0.3,
    metalness: 0.0
  });
  const mesh = new THREE.Mesh(geom, mat);
  mesh.position.fromArray(pos);
  scene.add(mesh);
  planes.push(mesh);
});

// Lighting for "light table" feel
const backLight = new THREE.PointLight(0xffffff, 2, 100);
backLight.position.z = 10;
const sideLight = new THREE.PointLight(0x007cba, 1.5, 100);
sideLight.position.x = -20;
scene.add(backLight, sideLight);

// Pointer drives parallax
document.addEventListener('mousemove', (e) => {
  const x = (e.clientX / window.innerWidth) * 2 - 1;
  const y = (e.clientY / window.innerHeight) * 2 - 1;
  
  planes.forEach((plane, i) => {
    plane.position.z -= x * 0.5; // parallax drift
    plane.rotation.y += x * 0.01;
  });
});
```

---

### 1.4 Immersive Stage (subject-forward, theatrical)

**Use when:** brief emphasizes "hero", "subject-centered", "theatrical", "spotlight".

**Key rules:**
- One central object/geometry is the focal point
- Theatrical lighting (key light, fill, back light)
- Camera orbits or tilts; viewer is "in the space"
- Identity encoded in the subject geometry and materials

```javascript
// Central subject (e.g., abstract form representing identity)
const subjectGeom = new THREE.OctahedronGeometry(2);
const subjectMat = new THREE.MeshStandardMaterial({
  color: 0x7a00df,
  roughness: 0.4,
  metalness: 0.6,
  emissive: 0x3a0066,
  emissiveIntensity: 0.3
});
const subject = new THREE.Mesh(subjectGeom, subjectMat);
scene.add(subject);

// Theatrical lights
const keyLight = new THREE.DirectionalLight(0xffffff, 2);
keyLight.position.set(5, 5, 5);

const fillLight = new THREE.DirectionalLight(0x007cba, 1);
fillLight.position.set(-10, 0, 0);

const backLight = new THREE.PointLight(0xff00ff, 1.5, 100);
backLight.position.set(0, 5, -10);

scene.add(keyLight, fillLight, backLight);

// Gentle rotating/tilting (responsive to pointer)
let targetRotX = 0, targetRotY = 0;
document.addEventListener('mousemove', (e) => {
  targetRotX = (e.clientY / h) * 0.3 - 0.15;
  targetRotY = (e.clientX / w) * 0.3 - 0.15;
});

function animate() {
  subject.rotation.x += (targetRotX - subject.rotation.x) * 0.05;
  subject.rotation.y += (targetRotY - subject.rotation.y) * 0.05;
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}
```

---

## 2. SVG + D3 Patterns

### 2.1 Interactive Network or Force-Directed Graph

**Use when:** brief involves "relationships", "networks", "systems", or relational data.

**Key libraries:** `svg.js` or raw SVG + `d3-force` (modular ESM from CDN).

```javascript
// Simulated identity data (or actual relationships from brief)
const nodes = [
  {id: 'design', label: 'Design'},
  {id: 'motion', label: 'Motion'},
  {id: 'interaction', label: 'Interaction'}
];
const links = [
  {source: 'design', target: 'motion'},
  {source: 'motion', target: 'interaction'},
  {source: 'interaction', target: 'design'}
];

// Inline SVG + D3 force simulation
const svg = d3.select('body').append('svg')
  .attr('width', 800)
  .attr('height', 600)
  .style('background', '#0a0e27');

const simulation = d3.forceSimulation(nodes)
  .force('link', d3.forceLink(links).id(d => d.id).distance(100))
  .force('charge', d3.forceManyBody().strength(-300))
  .force('center', d3.forceCenter(400, 300));

const link = svg.selectAll('line')
  .data(links)
  .join('line')
  .attr('stroke', '#7a00df')
  .attr('stroke-width', 2);

const node = svg.selectAll('circle')
  .data(nodes)
  .join('circle')
  .attr('r', 25)
  .attr('fill', '#007cba')
  .call(d3.drag()
    .on('start', dragStarted)
    .on('drag', dragged)
    .on('end', dragEnded));

const label = svg.selectAll('text')
  .data(nodes)
  .join('text')
  .attr('text-anchor', 'middle')
  .attr('dy', '.3em')
  .text(d => d.label)
  .attr('fill', '#fff')
  .attr('font-size', '12px');

simulation.on('tick', () => {
  link
    .attr('x1', d => d.source.x)
    .attr('y1', d => d.source.y)
    .attr('x2', d => d.target.x)
    .attr('y2', d => d.target.y);
  
  node
    .attr('cx', d => d.x)
    .attr('cy', d => d.y);
  
  label
    .attr('x', d => d.x)
    .attr('y', d => d.y);
});

function dragStarted(event, d) {
  if (!event.active) simulation.alphaTarget(0.3).restart();
  d.fx = d.x;
  d.fy = d.y;
}

function dragged(event, d) {
  d.fx = event.x;
  d.fy = event.y;
}

function dragEnded(event, d) {
  if (!event.active) simulation.alphaTarget(0);
  d.fx = null;
  d.fy = null;
}
```

---

### 2.2 Parametric SVG Paths (complex shapes)

**Use when:** brief calls for "organic", "algorithmic", "parametric" forms + SVG.

**Libraries:** `svg.js` for creation; `paths.js` for path generation (optional, or roll your own with Path2D / SVG path commands).

```javascript
// Generate parametric SVG shapes
const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
svg.setAttribute('width', '800');
svg.setAttribute('height', '600');
svg.setAttribute('viewBox', '0 0 800 600');

// Lissajous curve (identity pattern generator)
const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
const points = [];
const a = 3, b = 2;
for (let t = 0; t < Math.PI * 2; t += 0.01) {
  const x = 400 + 150 * Math.sin(a * t);
  const y = 300 + 150 * Math.sin(b * t);
  points.push([x, y]);
}
const pathData = 'M' + points.map(p => p.join(',')).join('L');
path.setAttribute('d', pathData);
path.setAttribute('stroke', '#7a00df');
path.setAttribute('stroke-width', '2');
path.setAttribute('fill', 'none');
svg.append(path);
document.body.append(svg);

// Animate parameter changes on interaction
document.addEventListener('mousemove', (e) => {
  const ratio = e.clientX / window.innerWidth;
  // Update a, b parameters and recompute path
});
```

---

## 3. Hybrid Patterns (Three.js + SVG)

### 3.1 3D Scene with SVG Overlay (UI / Annotation)

**Use when:** primary experience is 3D but you need 2D UI or annotations (e.g., labels, connections).

**Structure:**
```html
<div style="position: relative; width: 100%; height: 100vh;">
  <canvas id="stage"></canvas> <!-- Three.js renders here -->
  <svg id="overlay"></svg>     <!-- SVG overlay for labels/annotations -->
</div>
```

**Pattern:**
```javascript
// Three.js scene (canvas)
const canvas = document.getElementById('stage');
const renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: true});
const scene = new THREE.Scene();
// ... scene setup ...

// SVG overlay (screen-space annotations)
const svgOverlay = document.getElementById('overlay');
svgOverlay.setAttribute('width', window.innerWidth);
svgOverlay.setAttribute('height', window.innerHeight);
svgOverlay.setAttribute('style', 'position: absolute; top: 0; left: 0;');

// When 3D object moves, project to screen space and update SVG label
function animateFrame() {
  // Three.js render
  renderer.render(scene, camera);
  
  // Project 3D positions to 2D screen space
  const screenPos = new THREE.Vector3();
  from3DObject.getWorldPosition(screenPos);
  screenPos.project(camera);
  const x = (screenPos.x * 0.5 + 0.5) * window.innerWidth;
  const y = -(screenPos.y * 0.5 - 0.5) * window.innerHeight;
  
  // Update SVG annotation
  const label = document.getElementById('label-3dobject');
  label.setAttribute('x', x);
  label.setAttribute('y', y);
  
  requestAnimationFrame(animateFrame);
}
```

---

## 4. Multi-Zone Patterns (single page, multiple immersive sections)

**Use when:** `build_spec.steps` requires multiple sections but you want to keep them in one HTML for evaluation coherence.

**Structure:**
```javascript
// Each zone is a separate Three.js scene or SVG, dynamically swapped
const zones = {
  'zone-hero': {
    scene: null,
    renderer: null,
    canvas: null,
    init: () => { /* setup */ },
    destroy: () => { /* cleanup */ },
    animate: () => { /* frame loop */ }
  },
  'zone-projects': {
    // ...
  },
  'zone-contact': {
    // ...
  }
};

// Scroll-trigger zone swaps
window.addEventListener('scroll', () => {
  const scrolled = window.scrollY;
  
  // Determine active zone
  if (scrolled < window.innerHeight) {
    activateZone('zone-hero');
  } else if (scrolled < window.innerHeight * 2) {
    activateZone('zone-projects');
  } else {
    activateZone('zone-contact');
  }
});

function activateZone(zoneId) {
  // Cleanup prior zone
  // Initialize new zone
  zones[zoneId].init();
  zones[zoneId].animate();
}
```

**Scene manifest for multi-zone:**
```json
{
  "kmbl_scene_manifest_v1": {
    "scene_topology": "multi_zone_sequential",
    "zones": [
      {"id": "zone-hero", "topology": "immersive_stage", "content": "identity intro"},
      {"id": "zone-projects", "topology": "constellation", "content": "project nodes"},
      {"id": "zone-contact", "topology": "editorial_cosmos", "content": "contact cues"}
    ],
    "zone_transitions": "scroll_triggered",
    "portfolio_shell_used": false
  }
}
```

---

## 5. Multi-Page Patterns (habitat_manifest_v2)

**Use when:** full experience cannot fit one page (token budget, complexity) and you need multi-run habitat.

**Approach:**

**Run 1 (primary immersive):**
```json
{
  "artifact_outputs": [
    {
      "role": "interactive_frontend_app_v1",
      "file_path": "component/preview/index.html",
      "content": "...primary constellation experience..."
    }
  ],
  "habitat_manifest_v2": {
    "primary_artifact_id": "run_1_artifact_0",
    "zones": [
      {
        "id": "projects",
        "topology": "constellation",
        "artifact_id": "run_1_artifact_0",
        "entry_point": "#projects"
      }
    ],
    "navigation_hints": {
      "next_zone_link": "/run_2_entry"
    }
  }
}
```

**Run 2 (secondary zone):**
```json
{
  "artifact_outputs": [
    {
      "role": "interactive_frontend_app_v1",
      "file_path": "component/preview/index.html",
      "content": "...editorial_cosmos process zone..."
    }
  ],
  "habitat_manifest_v2": {
    "parent_artifact_id": "run_1_artifact_0",
    "sequence_order": 2,
    "zones": [
      {
        "id": "process",
        "topology": "editorial_cosmos",
        "artifact_id": "run_2_artifact_0"
      }
    ],
    "navigation_hints": {
      "prev_zone_link": "/run_1_entry",
      "next_zone_link": "/run_3_entry"
    }
  }
}
```

---

## When to Use Each Pattern

| Pattern | Identity Signal | Tech | Complexity | Tokens |
|---------|---|---|---|---|
| **Constellation** | networked, relational | Three.js | Medium | ~2K |
| **Editorial Cosmos** | minimal, moody, vast | Three.js + TextGeometry | Medium | ~3K |
| **Light Table** | photography, archival | Three.js + TextureLoader | Medium | ~2.5K |
| **Immersive Stage** | hero, theatrical | Three.js + advanced lighting | High | ~2.5K |
| **Force Graph** | systems, relationships | D3 + SVG | Medium | ~1.5K |
| **Parametric SVG** | organic, algorithmic | SVG + Path2D | Low-Medium | ~1K |
| **Hybrid 3D+SVG** | mixed (3D data + 2D UI) | Three.js + SVG | High | ~3K+ |
| **Multi-Zone** | complex identity (stages) | Multiple techs | High | ~4-6K |
| **Habitat Multi-Run** | very complex identity | Batched runs | Very High | ~6-10K total |

---

## Avoiding Common Mistakes

❌ **Do NOT:**
- Use TorusKnotGeometry without identity justification
- Stack portfolio shell + 3D canvas (either/or)
- Enable OrbitControls if interaction isn't narrative
- Emit multi-zone without scroll structure or zone activation logic
- Leave canvas black or unlit

✅ **DO:**
- Choose one topology and commit
- Ground all geometry/color/motion in the identity brief
- Use Reduced-motion fallback
- Emit scene manifest with correct `portfolio_shell_used: false`
- Test canvas render before shipping

---

## References

- **GEOMETRY.md** — Scene topology definitions and composition rules
- **LIBRARIES.md** — Library stack policy per geometry mode
- **EVALUATOR_GUIDANCE.md** — What passes evaluation (scene manifest, identity grounding, interactivity)
- **CDN resources:**
  - Three.js: `https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js`
  - D3: `https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js`
  - GSAP: `https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js` (includes ScrollTrigger; load separately if needed)
  - svg.js: `https://cdn.jsdelivr.net/npm/svg.js@3`
