"""
Unit tests for habitat assembly.

Tests the habitat manifest parsing, section rendering, and assembly pipeline.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from kmbl_orchestrator.contracts.habitat_manifest_v2 import (
    HabitatManifestV2,
    HabitatPage,
    HabitatSection,
    FrameworkConfig,
    LayoutConfig,
    NavItem,
    normalize_habitat_manifest,
    extract_habitat_manifest,
)
from kmbl_orchestrator.contracts.image_artifact_v1 import (
    ImageArtifactV1,
    normalize_image_artifact,
)
from kmbl_orchestrator.contracts.content_block_v1 import (
    ContentBlockV1,
    normalize_content_block,
)
from kmbl_orchestrator.habitat.assembler import (
    assemble_habitat,
    merge_assembled_artifacts,
    AssemblyContext,
)
from kmbl_orchestrator.habitat.sanitizer import (
    sanitize_raw_html,
    sanitize_custom_css,
    sanitize_custom_js,
)
from kmbl_orchestrator.habitat.section_renderers import (
    render_section,
    RenderContext,
)
from kmbl_orchestrator.habitat.framework_cdns import (
    get_framework_cdn_urls,
    get_library_cdn_url,
    render_daisyui_component,
)


class TestHabitatManifestV2:
    def test_minimal_manifest(self):
        manifest = HabitatManifestV2(
            role="habitat_manifest_v2",
            name="Test Site",
            slug="test-site",
            pages=[
                HabitatPage(
                    slug="/",
                    title="Home",
                    sections=[],
                )
            ],
        )
        assert manifest.name == "Test Site"
        assert manifest.slug == "test-site"
        assert len(manifest.pages) == 1

    def test_full_manifest(self):
        manifest = HabitatManifestV2(
            role="habitat_manifest_v2",
            name="Jane's Portfolio",
            slug="jane-portfolio",
            framework=FrameworkConfig(base="daisyui", version="4.7.2", theme="corporate"),
            layout=LayoutConfig(
                nav=[
                    NavItem(label="Home", href="/"),
                    NavItem(label="About", href="/about"),
                ],
                footer="© 2026 Jane Doe",
                brand="Jane Doe",
            ),
            custom_css=".hero { background: blue; }",
            pages=[
                HabitatPage(
                    slug="/",
                    title="Home",
                    sections=[
                        HabitatSection(type="component", key="hero", component="hero", props={"heading": "Welcome"}),
                    ],
                ),
                HabitatPage(
                    slug="/about",
                    title="About",
                    sections=[
                        HabitatSection(type="raw_html", key="bio", content="<p>About me</p>"),
                    ],
                ),
            ],
        )
        assert manifest.framework.base == "daisyui"
        assert len(manifest.pages) == 2
        assert manifest.layout.brand == "Jane Doe"

    def test_manifest_requires_home_page(self):
        with pytest.raises(ValueError, match="home page"):
            HabitatManifestV2(
                role="habitat_manifest_v2",
                name="Test",
                slug="test",
                pages=[
                    HabitatPage(slug="/about", title="About", sections=[]),
                ],
            )

    def test_manifest_unique_page_slugs(self):
        with pytest.raises(ValueError, match="unique"):
            HabitatManifestV2(
                role="habitat_manifest_v2",
                name="Test",
                slug="test",
                pages=[
                    HabitatPage(slug="/", title="Home", sections=[]),
                    HabitatPage(slug="/", title="Home2", sections=[]),
                ],
            )

    def test_normalize_habitat_manifest(self):
        raw = {
            "role": "habitat_manifest_v2",
            "name": "Test",
            "slug": "test",
            "pages": [{"slug": "/", "title": "Home", "sections": []}],
        }
        manifest = normalize_habitat_manifest(raw)
        assert manifest is not None
        assert manifest.name == "Test"

    def test_extract_habitat_manifest(self):
        artifacts = [
            {"role": "other_artifact"},
            {
                "role": "habitat_manifest_v2",
                "name": "Test",
                "slug": "test",
                "pages": [{"slug": "/", "title": "Home", "sections": []}],
            },
        ]
        manifest = extract_habitat_manifest(artifacts)
        assert manifest is not None
        assert manifest.slug == "test"


class TestImageArtifactV1:
    def test_valid_image_artifact(self):
        artifact = ImageArtifactV1(
            role="image_artifact_v1",
            key="hero-image",
            url="https://example.com/image.jpg",
            alt="Hero image",
            source="external",
        )
        assert artifact.key == "hero-image"
        assert artifact.source == "external"

    def test_generated_image_artifact(self):
        artifact = ImageArtifactV1(
            role="image_artifact_v1",
            key="gen-image",
            url="https://cdn.openai.com/generated/abc.png",
            alt="Generated art",
            source="generated",
            generation_prompt="A beautiful sunset",
            placement_hint="hero",
        )
        assert artifact.source == "generated"
        assert artifact.generation_prompt == "A beautiful sunset"

    def test_normalize_image_artifact(self):
        raw = {
            "role": "image_artifact_v1",
            "key": "test",
            "url": "https://example.com/img.jpg",
            "alt": "Test",
            "source": "external",
        }
        normalized = normalize_image_artifact(raw)
        assert normalized is not None
        assert normalized["key"] == "test"


class TestContentBlockV1:
    def test_valid_content_block(self):
        block = ContentBlockV1(
            role="content_block_v1",
            key="intro",
            content_type="paragraph",
            content="This is a test paragraph.",
            source="provided",
        )
        assert block.key == "intro"
        assert block.content_type == "paragraph"

    def test_heading_content_block(self):
        block = ContentBlockV1(
            role="content_block_v1",
            key="title",
            content_type="heading",
            content="Welcome to My Site",
            source="generated",
            level=1,
        )
        assert block.level == 1

    def test_normalize_content_block(self):
        raw = {
            "role": "content_block_v1",
            "key": "test",
            "content_type": "paragraph",
            "content": "Test content",
            "source": "provided",
        }
        normalized = normalize_content_block(raw)
        assert normalized is not None
        assert normalized["content"] == "Test content"


class TestSanitizer:
    def test_sanitize_raw_html_removes_script(self):
        html = '<div>Safe</div><script>alert("evil")</script><p>Also safe</p>'
        sanitized = sanitize_raw_html(html)
        assert "<script>" not in sanitized
        assert "Safe" in sanitized
        assert "Also safe" in sanitized

    def test_sanitize_raw_html_removes_onclick(self):
        html = '<div onclick="evil()">Click</div>'
        sanitized = sanitize_raw_html(html)
        assert "onclick" not in sanitized
        assert "Click" in sanitized

    def test_sanitize_raw_html_preserves_safe_content(self):
        html = '<div class="card"><h1>Title</h1><p>Content</p></div>'
        sanitized = sanitize_raw_html(html)
        assert "card" in sanitized
        assert "Title" in sanitized

    def test_sanitize_custom_css_scopes_selectors(self):
        css = ".card { color: red; } .button { background: blue; }"
        scoped = sanitize_custom_css(css, "section-123")
        assert "#section-123 .card" in scoped
        assert "#section-123 .button" in scoped

    def test_sanitize_custom_js_wraps_in_iife(self):
        js = "console.log('hello');"
        wrapped = sanitize_custom_js(js, "section-123")
        assert "(function()" in wrapped
        assert "getElementById('section-123')" in wrapped
        assert "console.log('hello')" in wrapped


class TestFrameworkCDNs:
    def test_get_framework_cdn_urls_daisyui(self):
        urls = get_framework_cdn_urls("daisyui", "4.7.2")
        assert "css" in urls
        assert "4.7.2" in urls["css"]
        assert "daisyui" in urls["css"]

    def test_get_library_cdn_url_threejs(self):
        config = get_library_cdn_url("threejs", "0.162.0")
        assert "js" in config
        assert "0.162.0" in config["js"]
        assert config.get("type") == "module"

    def test_render_daisyui_component_hero(self):
        html = render_daisyui_component("hero", {
            "heading": "Welcome",
            "subheading": "Test subheading",
        })
        assert "Welcome" in html
        assert "Test subheading" in html
        assert "hero" in html


class TestSectionRenderers:
    def test_render_component_section(self):
        section = HabitatSection(
            type="component",
            key="hero-section",
            component="hero",
            props={"heading": "Test", "subheading": "Subtest"},
        )
        context = RenderContext(
            habitat_slug="test",
            page_slug="/",
            framework="daisyui",
        )
        html = render_section(section, context)
        assert "hero-section" in html
        assert "Test" in html

    def test_render_raw_html_section(self):
        section = HabitatSection(
            type="raw_html",
            key="custom-section",
            content="<div>Custom content</div>",
        )
        context = RenderContext(
            habitat_slug="test",
            page_slug="/",
            framework="daisyui",
        )
        html = render_section(section, context)
        assert "custom-section" in html
        assert "Custom content" in html


class TestHabitatAssembler:
    def test_assemble_minimal_habitat(self):
        manifest = HabitatManifestV2(
            role="habitat_manifest_v2",
            name="Test Site",
            slug="test-site",
            pages=[
                HabitatPage(
                    slug="/",
                    title="Home",
                    sections=[
                        HabitatSection(type="raw_html", key="content", content="<h1>Hello</h1>"),
                    ],
                )
            ],
        )
        artifacts = assemble_habitat(manifest)
        
        assert len(artifacts) >= 2
        
        html_artifacts = [a for a in artifacts if a.get("language") == "html"]
        css_artifacts = [a for a in artifacts if a.get("language") == "css"]
        
        assert len(html_artifacts) >= 1
        assert len(css_artifacts) >= 1
        
        index_html = next((a for a in html_artifacts if "index.html" in a.get("path", "")), None)
        assert index_html is not None
        assert index_html.get("entry_for_preview") is True
        assert "Hello" in index_html.get("content", "")

    def test_assemble_multi_page_habitat(self):
        manifest = HabitatManifestV2(
            role="habitat_manifest_v2",
            name="Multi Page Site",
            slug="multi-page",
            layout=LayoutConfig(
                nav=[
                    NavItem(label="Home", href="/"),
                    NavItem(label="About", href="/about"),
                ],
                footer="Footer text",
            ),
            pages=[
                HabitatPage(slug="/", title="Home", sections=[]),
                HabitatPage(slug="/about", title="About", sections=[]),
            ],
        )
        artifacts = assemble_habitat(manifest)
        
        html_artifacts = [a for a in artifacts if a.get("language") == "html"]
        assert len(html_artifacts) == 2
        
        paths = [a.get("path") for a in html_artifacts]
        assert any("index.html" in p for p in paths)
        assert any("about.html" in p for p in paths)

    def test_merge_assembled_artifacts(self):
        original = [
            {"role": "habitat_manifest_v2", "name": "Test", "slug": "test"},
            {"role": "other_artifact", "data": "preserved"},
        ]
        assembled = [
            {"role": "static_frontend_file_v1", "path": "component/test/index.html"},
        ]
        merged = merge_assembled_artifacts(original, assembled)
        
        assert any(a.get("role") == "other_artifact" for a in merged)
        assert any(a.get("role") == "static_frontend_file_v1" for a in merged)
        assert not any(a.get("role") == "habitat_manifest_v2" for a in merged)


class TestNormalizeIntegration:
    def test_habitat_assembly_in_generator_normalize(self):
        from kmbl_orchestrator.normalize.generator import normalize_generator_output
        
        raw = {
            "artifact_outputs": [
                {
                    "role": "habitat_manifest_v2",
                    "name": "Test Site",
                    "slug": "test-site",
                    "pages": [
                        {
                            "slug": "/",
                            "title": "Home",
                            "sections": [
                                {"type": "raw_html", "key": "content", "content": "<h1>Test</h1>"}
                            ],
                        }
                    ],
                }
            ],
            "proposed_changes": {},
            "updated_state": {},
        }
        
        candidate = normalize_generator_output(
            raw,
            thread_id=uuid4(),
            graph_run_id=uuid4(),
            generator_invocation_id=uuid4(),
            build_spec_id=uuid4(),
        )
        
        static_files = [
            a for a in candidate.artifact_refs_json
            if isinstance(a, dict) and a.get("role") == "static_frontend_file_v1"
        ]
        assert len(static_files) >= 1
        
        html_file = next((f for f in static_files if f.get("language") == "html"), None)
        assert html_file is not None
        assert "Test" in html_file.get("content", "")
