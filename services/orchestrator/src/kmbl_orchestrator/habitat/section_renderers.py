"""
Section renderers for habitat assembly.

Handles all section types:
- Layer 1: component (framework components)
- Layer 2: threejs_scene, spline_embed, lottie
- Layer 3: raw_html, raw_css, raw_js
- Content: generated_image, generated_text
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from kmbl_orchestrator.habitat.framework_cdns import (
    THREEJS_PRESETS,
    render_daisyui_component,
)
from kmbl_orchestrator.habitat.sanitizer import (
    sanitize_custom_css,
    sanitize_custom_js,
    sanitize_raw_html,
)

if TYPE_CHECKING:
    from kmbl_orchestrator.providers.image.service import ImageService
    from kmbl_orchestrator.contracts.image_artifact_v1 import ImageArtifactV1

_log = logging.getLogger(__name__)


@dataclass
class RenderContext:
    """Context passed to section renderers."""

    habitat_slug: str
    page_slug: str
    framework: str
    libraries: list[str] = field(default_factory=list)
    identity_context: dict[str, Any] | None = None
    
    # Image generation context
    image_service: ImageService | None = None
    graph_run_id: UUID | None = None
    thread_id: UUID | None = None
    identity_id: UUID | None = None
    
    # Collector for generated image artifacts
    generated_images: list[ImageArtifactV1] = field(default_factory=list)


def render_section(section: Any, context: RenderContext) -> str:
    """
    Render a habitat section to HTML.

    Args:
        section: HabitatSection object (or dict)
        context: Render context with habitat info

    Returns:
        Rendered HTML string for the section
    """
    if hasattr(section, "model_dump"):
        section_dict = section.model_dump()
    elif isinstance(section, dict):
        section_dict = section
    else:
        return f"<!-- Invalid section type: {type(section)} -->"

    section_type = section_dict.get("type", "")
    section_key = section_dict.get("key", "section")

    renderers = {
        "component": _render_component_section,
        "threejs_scene": _render_threejs_section,
        "spline_embed": _render_spline_section,
        "lottie": _render_lottie_section,
        "generated_image": _render_generated_image_section,
        "generated_text": _render_generated_text_section,
        "raw_html": _render_raw_html_section,
        "raw_css": _render_raw_css_section,
        "raw_js": _render_raw_js_section,
    }

    renderer = renderers.get(section_type)
    if not renderer:
        return f"<!-- Unknown section type: {section_type} -->"

    try:
        content = renderer(section_dict, context)
        return f'<section id="{section_key}" class="habitat-section habitat-section-{section_type}">\n{content}\n</section>'
    except Exception as exc:
        _log.warning("Section render failed for %s: %s", section_key, exc)
        return f"<!-- Section render error: {section_key} -->"


def _render_component_section(section: dict[str, Any], context: RenderContext) -> str:
    """Render a framework component section."""
    component = section.get("component", "")
    props = section.get("props", {})

    if context.framework == "daisyui":
        return render_daisyui_component(component, props)

    return f"<div data-component=\"{component}\">{props.get('content', '')}</div>"


def _render_threejs_section(section: dict[str, Any], context: RenderContext) -> str:
    """Render a Three.js scene section."""
    section_key = section.get("key", "threejs")
    config = section.get("config", {})
    preset = config.get("preset", "particles")

    canvas_id = f"{section_key}-canvas"
    height = config.get("height", "50vh")

    if preset == "custom":
        setup_js = config.get("setup_js", "")
        animate_js = config.get("animate_js", "")
        js_code = f"""
(function() {{
  const container = document.getElementById('{canvas_id}');
  if (!container || typeof THREE === 'undefined') return;
  
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(75, container.clientWidth / container.clientHeight, 0.1, 1000);
  const renderer = new THREE.WebGLRenderer({{ alpha: true, antialias: true }});
  renderer.setSize(container.clientWidth, container.clientHeight);
  container.appendChild(renderer.domElement);
  
  {setup_js}
  
  function animate() {{
    requestAnimationFrame(animate);
    {animate_js}
    renderer.render(scene, camera);
  }}
  animate();
}})();
"""
    elif preset in THREEJS_PRESETS:
        template = THREEJS_PRESETS[preset]
        js_code = template.format(
            section_id=canvas_id,
            color=config.get("color", "#667eea"),
            secondary_color=config.get("secondary_color", "#764ba2"),
            count=config.get("count", 500),
            speed=config.get("speed", 0.5),
        )
    else:
        js_code = f"console.warn('Unknown Three.js preset: {preset}');"

    return f"""
<div id="{canvas_id}" style="width: 100%; height: {height}; position: relative;"></div>
<script type="module">
import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.162.0/build/three.module.js';
window.THREE = THREE;
{js_code}
</script>
"""


def _render_spline_section(section: dict[str, Any], context: RenderContext) -> str:
    """Render a Spline 3D embed section."""
    section_key = section.get("key", "spline")
    config = section.get("config", {})
    scene_url = config.get("scene_url", "")
    height = config.get("height", "400px")

    if not scene_url:
        return "<!-- Spline: missing scene_url -->"

    canvas_id = f"{section_key}-spline"

    return f"""
<div id="{canvas_id}" style="width: 100%; height: {height}; position: relative;"></div>
<script type="module">
import {{ Application }} from 'https://unpkg.com/@splinetool/runtime@1.0.74/build/runtime.js';

const canvas = document.createElement('canvas');
canvas.style.width = '100%';
canvas.style.height = '100%';
document.getElementById('{canvas_id}').appendChild(canvas);

const app = new Application(canvas);
app.load('{scene_url}');
</script>
"""


def _render_lottie_section(section: dict[str, Any], context: RenderContext) -> str:
    """Render a Lottie animation section."""
    section_key = section.get("key", "lottie")
    config = section.get("config", {})
    animation_url = config.get("animation_url", "")
    loop = config.get("loop", True)
    autoplay = config.get("autoplay", True)
    height = config.get("height", "300px")

    if not animation_url:
        return "<!-- Lottie: missing animation_url -->"

    container_id = f"{section_key}-lottie"

    return f"""
<div id="{container_id}" style="width: 100%; height: {height};"></div>
<script>
document.addEventListener('DOMContentLoaded', function() {{
  if (typeof lottie === 'undefined') {{
    console.warn('Lottie library not loaded');
    return;
  }}
  lottie.loadAnimation({{
    container: document.getElementById('{container_id}'),
    renderer: 'svg',
    loop: {str(loop).lower()},
    autoplay: {str(autoplay).lower()},
    path: '{animation_url}'
  }});
}});
</script>
"""


def _render_generated_image_section(section: dict[str, Any], context: RenderContext) -> str:
    """
    Render a generated image section.

    If ImageService is available and prompt is provided, generates the image.
    Otherwise renders a placeholder.
    """
    section_key = section.get("key", "image")
    config = section.get("config", {})
    
    image_url = config.get("url", "")
    alt = config.get("alt", config.get("prompt", "Generated image"))
    placement = config.get("placement", "inline")
    prompt = config.get("prompt", "")
    style = config.get("style", "digital-art")
    size = config.get("size", "1024x1024")

    # Try to generate image if we have a service and prompt but no URL
    if not image_url and prompt and context.image_service:
        from kmbl_orchestrator.providers.image.service import HabitatImageRequest
        
        try:
            request = HabitatImageRequest(
                prompt=prompt,
                style=style,
                size=size,
                placement=placement,
                key=section_key,
                alt=alt,
                graph_run_id=context.graph_run_id,
                thread_id=context.thread_id,
                identity_id=context.identity_id,
            )
            
            # Use kiloclaw mode (routes to kmbl-image-gen agent)
            mode = "kiloclaw" if context.graph_run_id and context.thread_id else "placeholder"
            result = context.image_service.generate_for_habitat(request, mode=mode)
            
            if result.status == "generated" and result.artifact:
                image_url = result.artifact.url
                context.generated_images.append(result.artifact)
                _log.info(
                    "Generated image for section %s: %s",
                    section_key,
                    image_url[:80] if image_url else "no url",
                )
            elif result.error:
                _log.warning(
                    "Image generation failed for section %s: %s",
                    section_key,
                    result.error,
                )
        except Exception as exc:
            _log.warning(
                "Image generation error for section %s: %s",
                section_key,
                exc,
            )

    # Render placeholder if still no URL
    if not image_url:
        prompt_display = prompt or "No prompt provided"
        return f"""
<div class="habitat-image-placeholder" style="width: 100%; min-height: 200px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); display: flex; align-items: center; justify-content: center; color: white; text-align: center; padding: 2rem;">
  <div>
    <p style="opacity: 0.8; font-size: 0.875rem;">Image will be generated</p>
    <p style="font-style: italic;">"{prompt_display[:100]}..."</p>
  </div>
</div>
"""

    # Render actual image
    import html as html_module
    safe_url = html_module.escape(image_url)
    safe_alt = html_module.escape(alt)
    
    if placement == "hero":
        return f'<img src="{safe_url}" alt="{safe_alt}" class="w-full h-auto object-cover" style="max-height: 60vh;" />'
    elif placement == "background":
        return f'<div style="background-image: url({safe_url}); background-size: cover; background-position: center; min-height: 400px;"></div>'
    elif placement == "card":
        return f'<figure class="rounded-lg overflow-hidden shadow-lg"><img src="{safe_url}" alt="{safe_alt}" class="w-full h-auto" /></figure>'
    else:
        return f'<img src="{safe_url}" alt="{safe_alt}" class="max-w-full h-auto" />'


def _render_generated_text_section(section: dict[str, Any], context: RenderContext) -> str:
    """
    Render a generated text section.

    Note: Actual text generation happens during habitat assembly.
    This renders a placeholder if content is not yet available.
    """
    config = section.get("config", {})
    
    content = config.get("content", "")
    
    if not content:
        intent = config.get("intent", "No intent provided")
        return f"""
<div class="habitat-text-placeholder prose" style="padding: 1rem; background: #f3f4f6; border-radius: 0.5rem;">
  <p style="opacity: 0.6; font-style: italic;">Content will be generated: "{intent[:100]}..."</p>
</div>
"""

    return f'<div class="prose lg:prose-xl">{content}</div>'


def _render_raw_html_section(section: dict[str, Any], context: RenderContext) -> str:
    """Render a raw HTML section with sanitization."""
    content = section.get("content", "")
    return sanitize_raw_html(content)


def _render_raw_css_section(section: dict[str, Any], context: RenderContext) -> str:
    """Render a raw CSS section with scoping."""
    section_key = section.get("key", "css")
    content = section.get("content", "")
    scoped_css = sanitize_custom_css(content, section_key)
    return f"<style>\n{scoped_css}\n</style>"


def _render_raw_js_section(section: dict[str, Any], context: RenderContext) -> str:
    """Render a raw JS section with IIFE wrapping."""
    section_key = section.get("key", "js")
    content = section.get("content", "")
    safe_js = sanitize_custom_js(content, section_key)
    return f"<script>\n{safe_js}\n</script>"
