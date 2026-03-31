"""
IdentityBrief — generator-actionable identity constraints.

This is the bridge that carries identity signals past the planner boundary.
The orchestrator builds this from persisted identity data and injects it
directly into GeneratorRoleInput and EvaluatorRoleInput, independently of
whatever the planner chose to transcribe into build_spec.

Design intent:
  - Every field must be directly actionable by a code generator
  - No prose interpretation — only concrete constraints
  - Empty / None fields are omitted from serialization (don't pollute context)
  - The planner still interprets identity for creative direction;
    this brief enforces identity fidelity at the generation layer
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IdentityBrief(BaseModel):
    """Generator-actionable identity constraints built by the orchestrator."""

    model_config = ConfigDict(extra="forbid")

    identity_id: str
    source_url: str

    # Core persona signals
    display_name: str | None = None
    role_or_title: str | None = None
    short_bio: str | None = None  # max 200 chars; use verbatim or as anchor copy

    # Visual constraints (directly actionable)
    palette_hex: list[str] = Field(
        default_factory=list,
        description="Hex color values extracted from the source site. Use at least one.",
    )
    primary_palette: list[str] = Field(
        default_factory=list,
        description="Top 3 palette colors in order of prominence.",
    )

    # Typography / tone
    tone_keywords: list[str] = Field(
        default_factory=list,
        description="Max 6 tone descriptors. Drive CSS/copy choices.",
    )
    aesthetic_keywords: list[str] = Field(
        default_factory=list,
        description="Visual aesthetic descriptors for layout/style choices.",
    )
    layout_hints: list[str] = Field(
        default_factory=list,
        description="Inferred layout patterns (e.g. 'portfolio', 'services', 'contact-focused').",
    )

    # Content anchors (use in headings / copy if possible)
    headings_sample: list[str] = Field(
        default_factory=list,
        description="Up to 5 headings from the source site. Reflect tone, not copy verbatim.",
        max_length=5,
    )
    must_mention: list[str] = Field(
        default_factory=list,
        description=(
            "Strings that should appear somewhere in the output "
            "(display_name, role_or_title, key project categories). "
            "Evaluator checks these."
        ),
    )

    # Image references
    image_refs: list[str] = Field(
        default_factory=list,
        description="Up to 8 image URLs from the source site. Use as visual reference or embed if appropriate.",
        max_length=8,
    )

    # Extraction quality
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Extraction confidence from IdentitySeed (0-1). Low = treat as partial signal.",
    )
    is_fallback: bool = Field(
        default=False,
        description="True when this brief was synthesized from a fallback profile, not a real scrape.",
    )

    def to_generator_payload(self) -> dict[str, Any]:
        """Compact dict for injection into GeneratorRoleInput.identity_brief."""
        d: dict[str, Any] = {
            "identity_id": self.identity_id,
            "source_url": self.source_url,
        }
        if self.display_name:
            d["display_name"] = self.display_name
        if self.role_or_title:
            d["role_or_title"] = self.role_or_title
        if self.short_bio:
            d["short_bio"] = self.short_bio[:200]
        if self.palette_hex:
            d["palette_hex"] = self.palette_hex[:6]
        if self.primary_palette:
            d["primary_palette"] = self.primary_palette[:3]
        if self.tone_keywords:
            d["tone_keywords"] = self.tone_keywords[:6]
        if self.aesthetic_keywords:
            d["aesthetic_keywords"] = self.aesthetic_keywords[:4]
        if self.layout_hints:
            d["layout_hints"] = self.layout_hints[:4]
        if self.headings_sample:
            d["headings_sample"] = self.headings_sample[:5]
        if self.must_mention:
            d["must_mention"] = self.must_mention[:8]
        if self.image_refs:
            d["image_refs"] = self.image_refs[:8]
        d["confidence"] = self.confidence
        if self.is_fallback:
            d["is_fallback"] = True
        return d

    def to_evaluator_payload(self) -> dict[str, Any]:
        """Compact dict for injection into EvaluatorRoleInput.identity_brief.

        Same as generator but also carries must_mention as checkable targets.
        """
        return self.to_generator_payload()


def build_identity_brief(
    identity_id: str,
    *,
    seed_data: dict[str, Any],
    profile_data: dict[str, Any],
    is_fallback: bool = False,
) -> IdentityBrief:
    """
    Build an IdentityBrief from persisted identity data.

    Args:
        identity_id: The identity UUID as string.
        seed_data: Merged data from IdentitySourceRecord.metadata_json
                   (has tone_keywords, aesthetic_keywords, extraction_confidence).
        profile_data: IdentityProfileRecord.facets_json
                      (has tone_keywords, aesthetic_keywords, palette_hints,
                       layout_hints, image_refs, etc from IdentitySeed.to_facets_json()).
        is_fallback: Whether this brief was built from a synthetic fallback profile.
    """
    # Build must_mention list from persona fields
    must_mention: list[str] = []
    display_name: str | None = None
    role_or_title: str | None = None
    short_bio: str | None = None

    # profile_data from facets_json has source-level fields when set via to_facets_json()
    # seed-level fields come from IdentitySourceRecord raw_text (first line = to_profile_summary())
    # We reconstruct from facets since that's what's persisted
    src_url = profile_data.get("source_url") or seed_data.get("source_url") or ""

    # Try to extract persona from seed metadata or profile summary
    raw_text: str = seed_data.get("raw_text") or ""
    if raw_text:
        # First segment of profile summary is display_name (role_or_title) — bio
        parts = raw_text.split(" — ", 1)
        name_part = parts[0].strip()
        if "(" in name_part:
            name_seg = name_part.split("(", 1)
            display_name = name_seg[0].strip() or None
            role_or_title = name_seg[1].rstrip(")").strip() or None
        else:
            display_name = name_part or None
        if len(parts) > 1:
            short_bio = parts[1].strip()[:200] or None

    if display_name:
        must_mention.append(display_name)
    if role_or_title:
        must_mention.append(role_or_title)

    # Extract project evidence for must_mention
    project_evidence: list[str] = profile_data.get("project_evidence") or []
    # Add first two project types as must_mention signals
    for ev in project_evidence[:2]:
        short = str(ev)[:60]
        if short and short not in must_mention:
            must_mention.append(short)

    # Palette
    palette_hints: list[str] = profile_data.get("palette_hints") or []
    # Hex colors only
    hex_colors = [h for h in palette_hints if isinstance(h, str) and h.startswith("#")]
    primary_palette = hex_colors[:3]
    all_palette = hex_colors[:6]

    tone_kw: list[str] = (
        profile_data.get("tone_keywords")
        or seed_data.get("tone_keywords")
        or []
    )
    aesthetic_kw: list[str] = (
        profile_data.get("aesthetic_keywords")
        or seed_data.get("aesthetic_keywords")
        or []
    )
    layout_hints: list[str] = profile_data.get("layout_hints") or []
    headings: list[str] = profile_data.get("headings") or []
    image_refs: list[str] = profile_data.get("image_refs") or []

    confidence = float(
        seed_data.get("extraction_confidence")
        or profile_data.get("confidence")
        or 0.0
    )

    return IdentityBrief(
        identity_id=identity_id,
        source_url=src_url,
        display_name=display_name,
        role_or_title=role_or_title,
        short_bio=short_bio,
        palette_hex=all_palette,
        primary_palette=primary_palette,
        tone_keywords=tone_kw[:6],
        aesthetic_keywords=aesthetic_kw[:4],
        layout_hints=layout_hints[:4],
        headings_sample=headings[:5],
        must_mention=must_mention[:8],
        image_refs=image_refs[:8],
        confidence=confidence,
        is_fallback=is_fallback,
    )


def build_identity_brief_from_repo(
    repo: Any,
    identity_id: "UUID",
) -> IdentityBrief | None:
    """
    Load identity data from repository and construct IdentityBrief.

    Returns None if no identity profile exists and fallback is not appropriate.
    """

    profile = repo.get_identity_profile(identity_id)
    sources = repo.list_identity_sources(identity_id)

    if profile is None and not sources:
        return None

    # Build seed_data from most recent source's metadata
    seed_data: dict[str, Any] = {}
    if sources:
        latest = sources[0]  # newest first
        seed_data = dict(latest.metadata_json or {})
        seed_data["raw_text"] = latest.raw_text or ""
        seed_data["source_url"] = latest.source_uri or ""

    profile_data: dict[str, Any] = {}
    is_fallback = False
    if profile:
        profile_data = dict(profile.facets_json or {})
        is_fallback = bool(profile_data.get("is_fallback"))
    else:
        # Profile missing but sources exist — use seed data only
        is_fallback = True

    return build_identity_brief(
        str(identity_id),
        seed_data=seed_data,
        profile_data=profile_data,
        is_fallback=is_fallback,
    )
