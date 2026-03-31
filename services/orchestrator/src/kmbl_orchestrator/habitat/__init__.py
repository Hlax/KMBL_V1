"""
Habitat assembly module: converts habitat manifests into static frontend files.

The habitat system provides 3 layers of capability:
- Layer 1: Framework Components (DaisyUI, Bootstrap, Pico)
- Layer 2: 3D/Interactive (Three.js, Spline, GSAP, Lottie, p5.js)
- Layer 3: Raw Injection (custom HTML/CSS/JS)
"""

from kmbl_orchestrator.habitat.assembler import assemble_habitat
from kmbl_orchestrator.habitat.framework_cdns import (
    DAISYUI_COMPONENTS,
    FRAMEWORK_CDNS,
    LIBRARY_CDNS,
    THREEJS_PRESETS,
    get_framework_cdn_urls,
    get_library_cdn_url,
)
from kmbl_orchestrator.habitat.sanitizer import (
    sanitize_custom_css,
    sanitize_custom_js,
    sanitize_raw_html,
)
from kmbl_orchestrator.habitat.section_renderers import render_section

__all__ = [
    "assemble_habitat",
    "render_section",
    "sanitize_raw_html",
    "sanitize_custom_css",
    "sanitize_custom_js",
    "FRAMEWORK_CDNS",
    "LIBRARY_CDNS",
    "DAISYUI_COMPONENTS",
    "THREEJS_PRESETS",
    "get_framework_cdn_urls",
    "get_library_cdn_url",
]
