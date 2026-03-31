"""
CDN URLs and component templates for CSS frameworks and JS libraries.

Supports:
- CSS Frameworks: DaisyUI (Tailwind), Bootstrap, Pico
- JS Libraries: Three.js, GSAP, Spline, Lottie, p5.js
"""

from __future__ import annotations

from typing import Any

FRAMEWORK_CDNS: dict[str, dict[str, str]] = {
    "daisyui": {
        "css": "https://cdn.jsdelivr.net/npm/daisyui@{version}/dist/full.min.css",
        "js": "https://cdn.tailwindcss.com",
        "default_version": "4.7.2",
    },
    "bootstrap": {
        "css": "https://cdn.jsdelivr.net/npm/bootstrap@{version}/dist/css/bootstrap.min.css",
        "js": "https://cdn.jsdelivr.net/npm/bootstrap@{version}/dist/js/bootstrap.bundle.min.js",
        "default_version": "5.3.3",
    },
    "pico": {
        "css": "https://cdn.jsdelivr.net/npm/@picocss/pico@{version}/css/pico.min.css",
        "default_version": "2.0.6",
    },
    "none": {},
}

LIBRARY_CDNS: dict[str, dict[str, str]] = {
    "threejs": {
        "js": "https://cdn.jsdelivr.net/npm/three@{version}/build/three.module.js",
        "type": "module",
        "default_version": "0.162.0",
    },
    "gsap": {
        "js": "https://cdn.jsdelivr.net/npm/gsap@{version}/dist/gsap.min.js",
        "default_version": "3.12.5",
    },
    "spline-runtime": {
        "js": "https://unpkg.com/@splinetool/runtime@{version}/build/runtime.js",
        "type": "module",
        "default_version": "1.0.74",
    },
    "lottie": {
        "js": "https://cdn.jsdelivr.net/npm/lottie-web@{version}/build/player/lottie.min.js",
        "default_version": "5.12.2",
    },
    "p5": {
        "js": "https://cdn.jsdelivr.net/npm/p5@{version}/lib/p5.min.js",
        "default_version": "1.9.0",
    },
}

DAISYUI_COMPONENTS: dict[str, str] = {
    "hero": """
<div class="hero min-h-[50vh] bg-base-200">
  <div class="hero-content text-center">
    <div class="max-w-md">
      <h1 class="text-5xl font-bold">{heading}</h1>
      <p class="py-6">{subheading}</p>
      {cta_html}
    </div>
  </div>
</div>
""",
    "hero-with-image": """
<div class="hero min-h-[60vh] bg-base-200">
  <div class="hero-content flex-col lg:flex-row-reverse">
    <img src="{image_url}" class="max-w-sm rounded-lg shadow-2xl" alt="{image_alt}" />
    <div>
      <h1 class="text-5xl font-bold">{heading}</h1>
      <p class="py-6">{subheading}</p>
      {cta_html}
    </div>
  </div>
</div>
""",
    "card": """
<div class="card bg-base-100 shadow-xl">
  {figure_html}
  <div class="card-body">
    <h2 class="card-title">{title}</h2>
    <p>{description}</p>
    {actions_html}
  </div>
</div>
""",
    "navbar": """
<div class="navbar bg-base-100">
  <div class="flex-1">
    <a class="btn btn-ghost text-xl" href="/">{brand}</a>
  </div>
  <div class="flex-none">
    <ul class="menu menu-horizontal px-1">
      {nav_items_html}
    </ul>
  </div>
</div>
""",
    "footer": """
<footer class="footer footer-center p-10 bg-base-200 text-base-content rounded">
  <nav class="grid grid-flow-col gap-4">
    {links_html}
  </nav>
  <aside>
    <p>{copyright}</p>
  </aside>
</footer>
""",
    "stats": """
<div class="stats shadow">
  {stat_items_html}
</div>
""",
    "stat-item": """
<div class="stat">
  <div class="stat-title">{title}</div>
  <div class="stat-value">{value}</div>
  <div class="stat-desc">{description}</div>
</div>
""",
    "feature-section": """
<section class="py-16 px-4">
  <div class="max-w-6xl mx-auto">
    <h2 class="text-3xl font-bold text-center mb-12">{heading}</h2>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-8">
      {features_html}
    </div>
  </div>
</section>
""",
    "feature-card": """
<div class="card bg-base-100">
  <div class="card-body items-center text-center">
    <div class="text-4xl mb-4">{icon}</div>
    <h3 class="card-title">{title}</h3>
    <p>{description}</p>
  </div>
</div>
""",
    "testimonial": """
<div class="card bg-base-100 shadow-xl">
  <div class="card-body">
    <p class="italic">"{quote}"</p>
    <div class="flex items-center mt-4">
      {avatar_html}
      <div class="ml-4">
        <p class="font-bold">{author}</p>
        <p class="text-sm opacity-70">{role}</p>
      </div>
    </div>
  </div>
</div>
""",
    "cta-section": """
<section class="py-16 px-4 bg-primary text-primary-content">
  <div class="max-w-4xl mx-auto text-center">
    <h2 class="text-3xl font-bold mb-4">{heading}</h2>
    <p class="mb-8">{subheading}</p>
    <a href="{button_href}" class="btn btn-secondary btn-lg">{button_text}</a>
  </div>
</section>
""",
    "contact-form": """
<section class="py-16 px-4">
  <div class="max-w-md mx-auto">
    <h2 class="text-3xl font-bold text-center mb-8">{heading}</h2>
    <form class="space-y-4">
      <div class="form-control">
        <label class="label"><span class="label-text">Name</span></label>
        <input type="text" placeholder="Your name" class="input input-bordered" />
      </div>
      <div class="form-control">
        <label class="label"><span class="label-text">Email</span></label>
        <input type="email" placeholder="your@email.com" class="input input-bordered" />
      </div>
      <div class="form-control">
        <label class="label"><span class="label-text">Message</span></label>
        <textarea class="textarea textarea-bordered h-24" placeholder="Your message"></textarea>
      </div>
      <button type="submit" class="btn btn-primary w-full">{button_text}</button>
    </form>
  </div>
</section>
""",
    "gallery": """
<section class="py-16 px-4">
  <div class="max-w-6xl mx-auto">
    <h2 class="text-3xl font-bold text-center mb-12">{heading}</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      {gallery_items_html}
    </div>
  </div>
</section>
""",
    "gallery-item": """
<figure class="relative overflow-hidden rounded-lg">
  <img src="{image_url}" alt="{alt}" class="w-full h-64 object-cover transition-transform hover:scale-105" />
  <figcaption class="absolute bottom-0 left-0 right-0 bg-black/50 text-white p-4">
    <h3 class="font-bold">{title}</h3>
  </figcaption>
</figure>
""",
    "text-section": """
<section class="py-16 px-4">
  <div class="max-w-3xl mx-auto prose lg:prose-xl">
    {content_html}
  </div>
</section>
""",
    "two-column": """
<section class="py-16 px-4">
  <div class="max-w-6xl mx-auto grid grid-cols-1 md:grid-cols-2 gap-12 items-center">
    <div>{left_html}</div>
    <div>{right_html}</div>
  </div>
</section>
""",
}

THREEJS_PRESETS: dict[str, str] = {
    "particles": """
(function() {
  const container = document.getElementById('{section_id}');
  if (!container) return;
  
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(75, container.clientWidth / container.clientHeight, 0.1, 1000);
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  container.appendChild(renderer.domElement);

  const geometry = new THREE.BufferGeometry();
  const vertices = [];
  for (let i = 0; i < {count}; i++) {
    vertices.push(
      (Math.random() - 0.5) * 100,
      (Math.random() - 0.5) * 100,
      (Math.random() - 0.5) * 100
    );
  }
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
  const material = new THREE.PointsMaterial({ color: '{color}', size: 0.5 });
  const points = new THREE.Points(geometry, material);
  scene.add(points);
  camera.position.z = 50;

  function animate() {
    requestAnimationFrame(animate);
    points.rotation.x += 0.001 * {speed};
    points.rotation.y += 0.002 * {speed};
    renderer.render(scene, camera);
  }
  animate();
  
  window.addEventListener('resize', () => {
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
  });
})();
""",
    "waves": """
(function() {
  const container = document.getElementById('{section_id}');
  if (!container) return;
  
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(75, container.clientWidth / container.clientHeight, 0.1, 1000);
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  container.appendChild(renderer.domElement);

  const geometry = new THREE.PlaneGeometry(100, 100, 50, 50);
  const material = new THREE.MeshBasicMaterial({ color: '{color}', wireframe: true });
  const plane = new THREE.Mesh(geometry, material);
  plane.rotation.x = -Math.PI / 2.5;
  scene.add(plane);
  camera.position.z = 50;
  camera.position.y = 20;

  let time = 0;
  function animate() {
    requestAnimationFrame(animate);
    time += 0.02 * {speed};
    const positions = plane.geometry.attributes.position;
    for (let i = 0; i < positions.count; i++) {
      const x = positions.getX(i);
      const y = positions.getY(i);
      positions.setZ(i, Math.sin(x * 0.1 + time) * 3 + Math.cos(y * 0.1 + time) * 3);
    }
    positions.needsUpdate = true;
    renderer.render(scene, camera);
  }
  animate();
})();
""",
    "gradient": """
(function() {
  const container = document.getElementById('{section_id}');
  if (!container) return;
  
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const renderer = new THREE.WebGLRenderer({ alpha: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  container.appendChild(renderer.domElement);

  const geometry = new THREE.PlaneGeometry(2, 2);
  const material = new THREE.ShaderMaterial({
    uniforms: {
      time: { value: 0 },
      color1: { value: new THREE.Color('{color}') },
      color2: { value: new THREE.Color('{secondary_color}') }
    },
    vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position, 1.0); }`,
    fragmentShader: `
      uniform float time;
      uniform vec3 color1;
      uniform vec3 color2;
      varying vec2 vUv;
      void main() {
        vec3 color = mix(color1, color2, vUv.y + sin(time + vUv.x * 3.0) * 0.1);
        gl_FragColor = vec4(color, 1.0);
      }
    `
  });
  const mesh = new THREE.Mesh(geometry, material);
  scene.add(mesh);

  function animate() {
    requestAnimationFrame(animate);
    material.uniforms.time.value += 0.01 * {speed};
    renderer.render(scene, camera);
  }
  animate();
})();
""",
    "geometry": """
(function() {
  const container = document.getElementById('{section_id}');
  if (!container) return;
  
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(75, container.clientWidth / container.clientHeight, 0.1, 1000);
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  container.appendChild(renderer.domElement);

  const geometry = new THREE.TorusKnotGeometry(10, 3, 100, 16);
  const material = new THREE.MeshNormalMaterial();
  const mesh = new THREE.Mesh(geometry, material);
  scene.add(mesh);
  camera.position.z = 30;

  function animate() {
    requestAnimationFrame(animate);
    mesh.rotation.x += 0.01 * {speed};
    mesh.rotation.y += 0.01 * {speed};
    renderer.render(scene, camera);
  }
  animate();
})();
""",
}


def get_framework_cdn_urls(framework: str, version: str) -> dict[str, str]:
    """Get CDN URLs for a CSS framework with version substituted."""
    if framework not in FRAMEWORK_CDNS:
        return {}

    config = FRAMEWORK_CDNS[framework]
    urls: dict[str, str] = {}

    if "css" in config:
        urls["css"] = config["css"].format(version=version)
    if "js" in config:
        urls["js"] = config["js"].format(version=version)

    return urls


def get_library_cdn_url(name: str, version: str) -> dict[str, Any]:
    """Get CDN URL and config for a JS library with version substituted."""
    if name not in LIBRARY_CDNS:
        return {}

    config = LIBRARY_CDNS[name]
    result: dict[str, Any] = {
        "js": config["js"].format(version=version),
    }
    if "type" in config:
        result["type"] = config["type"]

    return result


def render_daisyui_component(component: str, props: dict[str, Any]) -> str:
    """Render a DaisyUI component with the given props."""
    if component not in DAISYUI_COMPONENTS:
        return f"<!-- Unknown component: {component} -->"

    template = DAISYUI_COMPONENTS[component]

    safe_props: dict[str, str] = {}
    for key, value in props.items():
        if isinstance(value, str):
            safe_props[key] = value
        elif isinstance(value, (int, float)):
            safe_props[key] = str(value)
        elif value is None:
            safe_props[key] = ""
        else:
            safe_props[key] = str(value)

    safe_props.setdefault("cta_html", "")
    safe_props.setdefault("figure_html", "")
    safe_props.setdefault("actions_html", "")
    safe_props.setdefault("nav_items_html", "")
    safe_props.setdefault("links_html", "")
    safe_props.setdefault("stat_items_html", "")
    safe_props.setdefault("features_html", "")
    safe_props.setdefault("gallery_items_html", "")
    safe_props.setdefault("content_html", "")
    safe_props.setdefault("left_html", "")
    safe_props.setdefault("right_html", "")
    safe_props.setdefault("avatar_html", "")
    safe_props.setdefault("heading", "")
    safe_props.setdefault("subheading", "")
    safe_props.setdefault("title", "")
    safe_props.setdefault("description", "")
    safe_props.setdefault("brand", "")
    safe_props.setdefault("copyright", "")
    safe_props.setdefault("button_text", "Submit")
    safe_props.setdefault("button_href", "#")
    safe_props.setdefault("image_url", "")
    safe_props.setdefault("image_alt", "")
    safe_props.setdefault("alt", "")
    safe_props.setdefault("quote", "")
    safe_props.setdefault("author", "")
    safe_props.setdefault("role", "")
    safe_props.setdefault("icon", "")
    safe_props.setdefault("value", "")

    try:
        return template.format(**safe_props)
    except KeyError as e:
        return f"<!-- Component {component} missing prop: {e} -->"
