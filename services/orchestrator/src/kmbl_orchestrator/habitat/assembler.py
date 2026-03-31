"""
Main habitat assembler: converts HabitatManifestV2 into static_frontend_file_v1 artifacts.

The assembler:
1. Generates CSS (framework + custom)
2. Generates JS (libraries + custom)
3. Builds shared layout template
4. Renders each page with its sections
5. Returns list of static_frontend_file_v1 artifacts
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from kmbl_orchestrator.contracts.habitat_manifest_v2 import (
    HabitatManifestV2,
    HabitatPage,
)
from kmbl_orchestrator.habitat.framework_cdns import (
    get_framework_cdn_urls,
    get_library_cdn_url,
)
from kmbl_orchestrator.habitat.section_renderers import RenderContext, render_section

if TYPE_CHECKING:
    from kmbl_orchestrator.providers.image.service import ImageService

_log = logging.getLogger(__name__)


@dataclass
class AssemblyContext:
    """Context for habitat assembly including optional providers."""

    identity_context: dict[str, Any] | None = None
    
    # Image generation support
    image_service: ImageService | None = None
    graph_run_id: UUID | None = None
    thread_id: UUID | None = None
    identity_id: UUID | None = None


def assemble_habitat(
    manifest: HabitatManifestV2,
    context: AssemblyContext | None = None,
) -> list[dict[str, Any]]:
    """
    Convert a habitat manifest into static_frontend_file_v1 artifacts.

    Args:
        manifest: Validated HabitatManifestV2
        context: Optional assembly context with identity info

    Returns:
        List of static_frontend_file_v1 artifact dicts (and image_artifact_v1 if generated)
    """
    context = context or AssemblyContext()
    artifacts: list[dict[str, Any]] = []

    # Create shared render context for all pages (allows image artifact collection)
    render_ctx = RenderContext(
        habitat_slug=manifest.slug,
        page_slug="/",
        framework=manifest.framework.base,
        libraries=[lib.name for lib in manifest.libraries],
        identity_context=context.identity_context,
        image_service=context.image_service,
        graph_run_id=context.graph_run_id,
        thread_id=context.thread_id,
        identity_id=context.identity_id,
    )

    css_content = _build_habitat_css(manifest)
    if css_content:
        artifacts.append({
            "role": "static_frontend_file_v1",
            "path": f"component/{manifest.slug}/styles.css",
            "language": "css",
            "content": css_content,
        })

    js_content = _build_habitat_js(manifest)
    if js_content:
        artifacts.append({
            "role": "static_frontend_file_v1",
            "path": f"component/{manifest.slug}/main.js",
            "language": "js",
            "content": js_content,
        })

    layout_template = _build_layout_template(manifest)

    for i, page in enumerate(manifest.pages):
        page_html = _render_page(page, layout_template, manifest, context, render_ctx)
        slug_path = "index" if page.slug == "/" else page.slug.strip("/").replace("/", "-")

        artifacts.append({
            "role": "static_frontend_file_v1",
            "path": f"component/{manifest.slug}/{slug_path}.html",
            "language": "html",
            "content": page_html,
            "entry_for_preview": (i == 0),
            "bundle_id": manifest.slug,
        })

    # Collect generated image artifacts
    for img_artifact in render_ctx.generated_images:
        artifacts.append(img_artifact.model_dump(mode="json"))

    _log.info(
        "Assembled habitat %s: %d pages, %d images, %d total artifacts",
        manifest.slug,
        len(manifest.pages),
        len(render_ctx.generated_images),
        len(artifacts),
    )

    return artifacts


def _build_habitat_css(manifest: HabitatManifestV2) -> str:
    """Build combined CSS for the habitat."""
    parts: list[str] = []

    parts.append(f"""/* Habitat: {manifest.name} */
/* Framework: {manifest.framework.base} {manifest.framework.version} */

.habitat-section {{
  position: relative;
}}

.habitat-image-placeholder {{
  animation: habitat-pulse 2s infinite;
}}

@keyframes habitat-pulse {{
  0%, 100% {{ opacity: 0.8; }}
  50% {{ opacity: 0.6; }}
}}
""")

    if manifest.custom_css:
        parts.append(f"\n/* Custom CSS */\n{manifest.custom_css}")

    return "\n".join(parts)


def _build_habitat_js(manifest: HabitatManifestV2) -> str:
    """Build combined JS for the habitat."""
    parts: list[str] = []

    parts.append(f"""// Habitat: {manifest.name}
'use strict';

document.addEventListener('DOMContentLoaded', function() {{
  console.log('Habitat loaded: {manifest.slug}');
}});
""")

    if manifest.custom_js:
        parts.append(f"\n// Custom JS\n{manifest.custom_js}")

    return "\n".join(parts)


def _build_layout_template(manifest: HabitatManifestV2) -> str:
    """Build the shared HTML layout template."""
    framework_urls = get_framework_cdn_urls(
        manifest.framework.base,
        manifest.framework.version,
    )

    head_links: list[str] = []
    body_scripts: list[str] = []

    if "css" in framework_urls:
        head_links.append(f'<link rel="stylesheet" href="{framework_urls["css"]}">')

    if "js" in framework_urls:
        body_scripts.append(f'<script src="{framework_urls["js"]}"></script>')

    head_links.append('<link rel="stylesheet" href="styles.css">')

    for lib in manifest.libraries:
        lib_config = get_library_cdn_url(lib.name, lib.version)
        if "js" in lib_config:
            script_type = lib_config.get("type", "")
            if script_type:
                body_scripts.append(f'<script type="{script_type}" src="{lib_config["js"]}"></script>')
            else:
                body_scripts.append(f'<script src="{lib_config["js"]}"></script>')

    body_scripts.append('<script src="main.js"></script>')

    nav_html = _render_nav(manifest)
    footer_html = _render_footer(manifest)

    if manifest.framework.base == "daisyui":
        theme_attr = f'data-theme="{manifest.framework.theme}"'
    else:
        theme_attr = ""

    return f"""<!DOCTYPE html>
<html lang="en" {theme_attr}>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{{{title}}}} - {html.escape(manifest.name)}</title>
  <meta name="description" content="{{{{meta_description}}}}">
  {chr(10).join(head_links)}
</head>
<body>
  {nav_html}
  <main>
    {{{{content}}}}
  </main>
  {footer_html}
  {chr(10).join(body_scripts)}
</body>
</html>
"""


def _render_nav(manifest: HabitatManifestV2) -> str:
    """Render the navigation bar."""
    if not manifest.layout.nav:
        return ""

    nav_items: list[str] = []
    for item in manifest.layout.nav:
        nav_items.append(f'<li><a href="{html.escape(item.href)}">{html.escape(item.label)}</a></li>')

    brand = manifest.layout.brand or manifest.name

    if manifest.framework.base == "daisyui":
        return f"""
<div class="navbar bg-base-100 shadow-lg">
  <div class="flex-1">
    <a class="btn btn-ghost text-xl" href="/">{html.escape(brand)}</a>
  </div>
  <div class="flex-none">
    <ul class="menu menu-horizontal px-1">
      {chr(10).join(nav_items)}
    </ul>
  </div>
</div>
"""
    else:
        return f"""
<nav style="padding: 1rem; background: #f3f4f6;">
  <a href="/" style="font-weight: bold; font-size: 1.25rem; margin-right: 2rem;">{html.escape(brand)}</a>
  <ul style="display: inline; list-style: none; margin: 0; padding: 0;">
    {chr(10).join(nav_items)}
  </ul>
</nav>
"""


def _render_footer(manifest: HabitatManifestV2) -> str:
    """Render the footer."""
    if not manifest.layout.footer:
        return ""

    if manifest.framework.base == "daisyui":
        return f"""
<footer class="footer footer-center p-10 bg-base-200 text-base-content rounded">
  <aside>
    <p>{html.escape(manifest.layout.footer)}</p>
  </aside>
</footer>
"""
    else:
        return f"""
<footer style="padding: 2rem; text-align: center; background: #f3f4f6; margin-top: 2rem;">
  <p>{html.escape(manifest.layout.footer)}</p>
</footer>
"""


def _render_page(
    page: HabitatPage,
    layout_template: str,
    manifest: HabitatManifestV2,
    context: AssemblyContext,
    shared_render_ctx: RenderContext,
) -> str:
    """Render a single page with its sections."""
    # Update page-specific context fields
    shared_render_ctx.page_slug = page.slug

    section_parts: list[str] = []
    for section in page.sections:
        rendered = render_section(section, shared_render_ctx)
        section_parts.append(rendered)

    content_html = "\n".join(section_parts)

    page_html = layout_template.replace("{{title}}", html.escape(page.title))
    page_html = page_html.replace("{{meta_description}}", html.escape(page.meta_description or ""))
    page_html = page_html.replace("{{content}}", content_html)

    return page_html


def merge_assembled_artifacts(
    original_artifacts: list[Any],
    assembled: list[dict[str, Any]],
) -> list[Any]:
    """
    Merge assembled habitat artifacts with original artifact list.

    Removes the habitat_manifest_v2 and adds the assembled files.
    """
    filtered = [
        a for a in original_artifacts
        if not (isinstance(a, dict) and a.get("role") == "habitat_manifest_v2")
    ]

    return filtered + assembled
