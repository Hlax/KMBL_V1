"""
Habitat Manifest v2: Multi-page website generation with 3-layer architecture.

Layer 1: Framework Components (DaisyUI, Bootstrap, Pico)
Layer 2: 3D/Interactive (Three.js, Spline, GSAP, Lottie, p5.js)
Layer 3: Raw Injection (custom HTML/CSS/JS)

The generator emits a habitat_manifest_v2 artifact, and KMBL assembles it
into static_frontend_file_v1 artifacts for preview and publication.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_log = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")
_PAGE_SLUG_RE = re.compile(r"^/[a-z0-9/-]*$|^/$")
_KEY_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


class FrameworkConfig(BaseModel):
    """CSS framework configuration for the habitat."""

    model_config = ConfigDict(extra="forbid")

    base: Literal["daisyui", "bootstrap", "pico", "none"] = "daisyui"
    version: str = Field(default="4.7.2", max_length=20)
    theme: str = Field(default="corporate", max_length=50)

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        if not re.match(r"^\d+\.\d+(\.\d+)?$", v):
            raise ValueError("version must be semver format (e.g., 4.7.2)")
        return v


class LibraryRef(BaseModel):
    """Reference to a 3D/interactive library loaded via CDN."""

    model_config = ConfigDict(extra="forbid")

    name: Literal["threejs", "gsap", "spline-runtime", "lottie", "p5"]
    version: str = Field(max_length=20)

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        if not re.match(r"^\d+\.\d+(\.\d+)?$", v):
            raise ValueError("version must be semver format")
        return v


class NavItem(BaseModel):
    """Navigation item for the habitat layout."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=50)
    href: str = Field(min_length=1, max_length=200)


class LayoutConfig(BaseModel):
    """Shared layout configuration for all pages."""

    model_config = ConfigDict(extra="forbid")

    nav: list[NavItem] = Field(default_factory=list)
    footer: str | None = Field(default=None, max_length=500)
    brand: str | None = Field(default=None, max_length=100)


class ComponentSectionProps(BaseModel):
    """Props for a framework component section."""

    model_config = ConfigDict(extra="allow")

    component: str = Field(min_length=1, max_length=50)


class ThreeJSSceneConfig(BaseModel):
    """Configuration for a Three.js scene section."""

    model_config = ConfigDict(extra="allow")

    preset: Literal["particles", "waves", "gradient", "geometry", "custom"] = "particles"
    color: str = Field(default="#667eea", max_length=20)
    secondary_color: str | None = Field(default=None, max_length=20)
    count: int = Field(default=500, ge=10, le=10000)
    speed: float = Field(default=0.5, ge=0.1, le=5.0)
    interactive: bool = False
    height: str = Field(default="50vh", max_length=20)
    setup_js: str | None = Field(default=None, max_length=10000)
    animate_js: str | None = Field(default=None, max_length=5000)


class SplineEmbedConfig(BaseModel):
    """Configuration for a Spline 3D embed."""

    model_config = ConfigDict(extra="forbid")

    scene_url: str = Field(min_length=1, max_length=500)
    height: str = Field(default="400px", max_length=20)


class LottieConfig(BaseModel):
    """Configuration for a Lottie animation."""

    model_config = ConfigDict(extra="forbid")

    animation_url: str = Field(min_length=1, max_length=500)
    loop: bool = True
    autoplay: bool = True
    height: str = Field(default="300px", max_length=20)


class GeneratedImageConfig(BaseModel):
    """Configuration for an AI-generated image section."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=1000)
    style: str = Field(default="digital-art", max_length=50)
    size: str = Field(default="1024x1024", max_length=20)
    placement: Literal["hero", "inline", "background", "card"] = "inline"


class GeneratedTextConfig(BaseModel):
    """Configuration for AI-generated text content."""

    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1, max_length=500)
    tone: str = Field(default="professional", max_length=50)
    length: str = Field(default="1-2 paragraphs", max_length=50)
    identity_context: bool = False


class HabitatSection(BaseModel):
    """A section within a habitat page."""

    model_config = ConfigDict(extra="allow")

    type: Literal[
        "component",
        "threejs_scene",
        "spline_embed",
        "lottie",
        "generated_image",
        "generated_text",
        "raw_html",
        "raw_css",
        "raw_js",
    ]
    key: str = Field(min_length=1, max_length=64)

    component: str | None = Field(default=None, max_length=50)
    props: dict[str, Any] = Field(default_factory=dict)

    config: dict[str, Any] = Field(default_factory=dict)

    content: str | None = Field(default=None, max_length=100000)

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        if not _KEY_RE.match(v):
            raise ValueError("key must be alphanumeric with underscores/hyphens, starting with letter")
        return v

    @model_validator(mode="after")
    def validate_section_type_requirements(self) -> HabitatSection:
        if self.type == "component" and not self.component:
            raise ValueError("component sections require 'component' field")
        if self.type in ("raw_html", "raw_css", "raw_js") and not self.content:
            raise ValueError(f"{self.type} sections require 'content' field")
        return self


class HabitatPage(BaseModel):
    """A page within the habitat."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    sections: list[HabitatSection] = Field(default_factory=list)
    meta_description: str | None = Field(default=None, max_length=300)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _PAGE_SLUG_RE.match(v):
            raise ValueError("page slug must start with / and contain only lowercase letters, numbers, hyphens")
        return v

    @model_validator(mode="after")
    def validate_unique_section_keys(self) -> HabitatPage:
        keys = [s.key for s in self.sections]
        if len(keys) != len(set(keys)):
            raise ValueError("section keys must be unique within a page")
        return self


class HabitatManifestV2(BaseModel):
    """
    Multi-page habitat manifest for website generation.

    The generator emits this as an artifact, and KMBL assembles it into
    static_frontend_file_v1 artifacts.
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["habitat_manifest_v2"]
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=50)
    framework: FrameworkConfig = Field(default_factory=FrameworkConfig)
    libraries: list[LibraryRef] = Field(default_factory=list)
    layout: LayoutConfig = Field(default_factory=LayoutConfig)
    custom_css: str | None = Field(default=None, max_length=50000)
    custom_js: str | None = Field(default=None, max_length=50000)
    pages: list[HabitatPage] = Field(min_length=1)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError("slug must be lowercase alphanumeric with hyphens")
        return v

    @model_validator(mode="after")
    def validate_unique_page_slugs(self) -> HabitatManifestV2:
        slugs = [p.slug for p in self.pages]
        if len(slugs) != len(set(slugs)):
            raise ValueError("page slugs must be unique within the habitat")
        if "/" not in slugs:
            raise ValueError("habitat must have a home page with slug '/'")
        return self


def normalize_habitat_manifest(item: dict[str, Any]) -> HabitatManifestV2 | None:
    """
    Validate and normalize a habitat manifest dict.

    Returns None if validation fails (logs warning).
    """
    if not isinstance(item, dict):
        return None
    if item.get("role") != "habitat_manifest_v2":
        return None

    try:
        return HabitatManifestV2.model_validate(item)
    except Exception as exc:
        _log.warning("habitat_manifest_v2 validation failed: %s", exc)
        return None


def extract_habitat_manifest(artifacts: list[Any]) -> HabitatManifestV2 | None:
    """
    Extract the first valid habitat manifest from artifact list.

    Returns None if no valid manifest found.
    """
    for item in artifacts:
        if isinstance(item, dict) and item.get("role") == "habitat_manifest_v2":
            manifest = normalize_habitat_manifest(item)
            if manifest:
                return manifest
    return None
