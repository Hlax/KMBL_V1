"""
Lightweight identity seed schema — the normalized output of website extraction.

Consumed by planner (via identity_context) and generator (via build_spec constraints).
Intentionally thin: partial seeds are valid. Future expansion adds richer visual
extraction, multi-page crawling, image remixing, etc.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IdentitySeed(BaseModel):
    """Structured identity signals extracted from a website URL."""

    model_config = ConfigDict(extra="forbid")

    source_url: str
    display_name: str | None = None
    role_or_title: str | None = None
    short_bio: str | None = None
    tone_keywords: list[str] = Field(default_factory=list)
    aesthetic_keywords: list[str] = Field(default_factory=list)
    palette_hints: list[str] = Field(default_factory=list)
    layout_hints: list[str] = Field(default_factory=list)
    project_evidence: list[str] = Field(default_factory=list)
    image_refs: list[str] = Field(default_factory=list)
    headings: list[str] = Field(default_factory=list)
    meta_description: str | None = None
    extraction_notes: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    crawled_pages: list[str] = Field(default_factory=list)  # URLs crawled during multi-page extraction

    def to_identity_context_dict(self) -> dict[str, Any]:
        """Flatten into the shape consumed by build_planner_identity_context merging."""
        d = self.model_dump(mode="json")
        d.pop("confidence", None)
        d.pop("extraction_notes", None)
        return d

    def to_facets_json(self) -> dict[str, Any]:
        """Build the facets_json for IdentityProfileRecord."""
        facets: dict[str, Any] = {"source_url": self.source_url}
        if self.tone_keywords:
            facets["tone_keywords"] = self.tone_keywords
        if self.aesthetic_keywords:
            facets["aesthetic_keywords"] = self.aesthetic_keywords
        if self.palette_hints:
            facets["palette_hints"] = self.palette_hints
        if self.layout_hints:
            facets["layout_hints"] = self.layout_hints
        if self.project_evidence:
            facets["project_evidence"] = self.project_evidence
        if self.image_refs:
            facets["image_refs"] = self.image_refs[:8]
        if self.crawled_pages:
            facets["crawled_pages"] = self.crawled_pages
        return facets

    def to_profile_summary(self) -> str:
        """Build a one-line profile summary."""
        parts: list[str] = []
        if self.display_name:
            parts.append(self.display_name)
        if self.role_or_title:
            parts.append(f"({self.role_or_title})")
        if self.short_bio:
            parts.append(f"— {self.short_bio[:120]}")
        if not parts:
            parts.append(f"Identity from {self.source_url}")
        return " ".join(parts)
