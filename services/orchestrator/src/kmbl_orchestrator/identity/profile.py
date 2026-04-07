"""
Structured Identity Profile — derived from IdentitySeed for intent-driven planning.

This module produces a normalized, structured representation of identity signals
that replaces semi-unstructured text throughout the planner → generator → evaluator
pipeline.  Every field is deterministic and derivable from existing IdentitySeed
data — no external services required.

The StructuredIdentityProfile is the single authoritative structured representation
of "who this identity is" for downstream nodes.  It travels alongside the existing
IdentityBrief (which carries generator-actionable constraints like palette_hex and
must_mention) but adds higher-level classification signals that inform planning
decisions such as experience_mode derivation.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_log = logging.getLogger(__name__)

# ── Vocabulary constants (deterministic, keyword-based) ──────────────────────

_THEME_KEYWORDS: dict[str, set[str]] = {
    "editorial": {"blog", "article", "writing", "editorial", "journal", "essay", "publication"},
    "cinematic": {"cinematic", "film", "video", "motion", "reel", "showreel", "trailer"},
    "minimal": {"minimal", "minimalist", "clean", "simple", "whitespace"},
    "experimental": {"experimental", "abstract", "generative", "creative coding", "glitch", "avant-garde"},
    "corporate": {"corporate", "enterprise", "business", "consulting", "solutions", "b2b"},
    "artistic": {"artistic", "art", "gallery", "exhibition", "installation", "studio"},
    "technical": {"technical", "engineering", "developer", "code", "api", "devops", "infrastructure"},
}

_TONE_KEYWORDS: dict[str, set[str]] = {
    "serious": {"serious", "professional", "corporate", "formal", "enterprise"},
    "playful": {"playful", "fun", "creative", "colorful", "vibrant", "friendly", "whimsical"},
    "abstract": {"abstract", "experimental", "generative", "conceptual", "avant-garde"},
    "technical": {"technical", "engineering", "developer", "code", "api", "documentation"},
    "warm": {"warm", "personal", "friendly", "approachable", "inviting", "cozy"},
    "bold": {"bold", "striking", "dramatic", "intense", "powerful", "dark"},
}

_VISUAL_TENDENCY_KEYWORDS: dict[str, set[str]] = {
    "motion-heavy": {"motion", "animation", "cinematic", "video", "reel", "showreel", "kinetic"},
    "typography-first": {"editorial", "writing", "blog", "journal", "text", "copy", "article"},
    "spatial": {
        "3d", "three.js", "webgl", "spatial", "immersive", "interactive",
        "gallery", "exhibition", "installation", "panorama",
    },
    "image-driven": {
        "photography", "photo", "photographer", "gallery", "portfolio",
        "visual", "image", "illustration", "artwork",
    },
}

_CONTENT_TYPE_KEYWORDS: dict[str, set[str]] = {
    "projects": {"project", "projects", "work", "portfolio", "case study", "case studies"},
    "writing": {"blog", "article", "writing", "essay", "journal", "publication", "post"},
    "photography": {"photography", "photo", "photographer", "shots", "captures", "lens"},
    "code": {"code", "github", "repository", "open source", "developer", "engineering"},
    "design": {"design", "designer", "ui", "ux", "interface", "graphic", "branding"},
    "art": {"art", "artwork", "illustration", "painting", "sculpture", "digital art"},
    "services": {"service", "services", "offering", "consulting", "agency", "freelance"},
}

_COMPLEXITY_SIGNALS_AMBITIOUS: set[str] = {
    "immersive", "interactive", "3d", "webgl", "three.js", "spatial",
    "experimental", "generative", "cinematic", "parallax", "animation",
    "multi-page", "gallery", "complex",
}

_COMPLEXITY_SIGNALS_SIMPLE: set[str] = {
    "minimal", "simple", "clean", "one-page", "landing", "basic",
    "text-only", "blog", "resume", "cv",
}


class StructuredIdentityProfile(BaseModel):
    """Normalized, structured identity signals for intent-driven pipeline propagation."""

    model_config = ConfigDict(extra="forbid")

    themes: list[str] = Field(
        default_factory=list,
        description="Identity themes: editorial, cinematic, minimal, experimental, corporate, artistic, technical.",
    )
    tone: list[str] = Field(
        default_factory=list,
        description="Tone signals: serious, playful, abstract, technical, warm, bold.",
    )
    visual_tendencies: list[str] = Field(
        default_factory=list,
        description="Visual tendencies: motion-heavy, typography-first, spatial, image-driven.",
    )
    content_types: list[str] = Field(
        default_factory=list,
        description="Content types: projects, writing, photography, code, design, art, services.",
    )
    complexity: str = Field(
        default="moderate",
        description="Complexity signal: simple, moderate, ambitious.",
    )
    notable_entities: list[str] = Field(
        default_factory=list,
        description="Notable entities: project names, collaborators, brands (max 10).",
    )

    def to_dict(self) -> dict[str, Any]:
        """Compact dict for payload injection — omits empty lists."""
        d: dict[str, Any] = {}
        if self.themes:
            d["themes"] = self.themes
        if self.tone:
            d["tone"] = self.tone
        if self.visual_tendencies:
            d["visual_tendencies"] = self.visual_tendencies
        if self.content_types:
            d["content_types"] = self.content_types
        d["complexity"] = self.complexity
        if self.notable_entities:
            d["notable_entities"] = self.notable_entities
        return d


def _match_keywords(text: str, vocab: dict[str, set[str]], max_matches: int = 4) -> list[str]:
    """Match text against a keyword vocabulary, return matching category labels."""
    lower = text.lower()
    scored: list[tuple[str, int]] = []
    for label, keywords in vocab.items():
        hits = sum(1 for kw in keywords if kw in lower)
        if hits > 0:
            scored.append((label, hits))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [label for label, _ in scored[:max_matches]]


def _match_keywords_weighted(
    text: str, vocab: dict[str, set[str]], max_matches: int = 4,
) -> list[tuple[str, int]]:
    """Match text against a keyword vocabulary, return (label, hit_count) pairs."""
    lower = text.lower()
    scored: list[tuple[str, int]] = []
    for label, keywords in vocab.items():
        hits = sum(1 for kw in keywords if kw in lower)
        if hits > 0:
            scored.append((label, hits))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:max_matches]


def extract_structured_identity(
    *,
    seed_data: dict[str, Any] | None = None,
    profile_data: dict[str, Any] | None = None,
    identity_brief: dict[str, Any] | None = None,
) -> StructuredIdentityProfile:
    """
    Derive a StructuredIdentityProfile from available identity data.

    This function is deterministic and does not call external services.
    It works from any combination of:
      - seed_data: IdentitySourceRecord.metadata_json + raw_text
      - profile_data: IdentityProfileRecord.facets_json
      - identity_brief: the already-built IdentityBrief payload dict

    All inputs are optional — partial extraction is valid.
    """
    sd = seed_data or {}
    pd = profile_data or {}
    ib = identity_brief or {}

    # Build a combined text corpus for keyword matching
    text_parts: list[str] = []
    raw_text = sd.get("raw_text") or ""
    if raw_text:
        text_parts.append(raw_text)

    # Aggregate keyword lists from all sources
    all_tone_kw: list[str] = (
        ib.get("tone_keywords")
        or pd.get("tone_keywords")
        or sd.get("tone_keywords")
        or []
    )
    all_aesthetic_kw: list[str] = (
        ib.get("aesthetic_keywords")
        or pd.get("aesthetic_keywords")
        or sd.get("aesthetic_keywords")
        or []
    )
    all_layout_hints: list[str] = ib.get("layout_hints") or pd.get("layout_hints") or []
    all_headings: list[str] = ib.get("headings_sample") or pd.get("headings") or []
    project_evidence: list[str] = pd.get("project_evidence") or []
    display_name: str = ib.get("display_name") or ""
    role_or_title: str = ib.get("role_or_title") or ""
    short_bio: str = ib.get("short_bio") or ""

    # Build searchable text from all signals
    text_parts.extend(all_tone_kw)
    text_parts.extend(all_aesthetic_kw)
    text_parts.extend(all_layout_hints)
    text_parts.extend(all_headings)
    text_parts.extend(project_evidence)
    if role_or_title:
        text_parts.append(role_or_title)
    if short_bio:
        text_parts.append(short_bio)

    combined_text = " ".join(text_parts)

    # ── Themes ───────────────────────────────────────────────────────────
    themes = _match_keywords(combined_text, _THEME_KEYWORDS, max_matches=3)

    # ── Tone ─────────────────────────────────────────────────────────────
    tone = _match_keywords(combined_text, _TONE_KEYWORDS, max_matches=3)

    # ── Visual tendencies ────────────────────────────────────────────────
    visual_tendencies = _match_keywords(
        combined_text, _VISUAL_TENDENCY_KEYWORDS, max_matches=3,
    )
    # Boost image-driven if image_refs are abundant
    image_refs = ib.get("image_refs") or pd.get("image_refs") or []
    if len(image_refs) >= 4 and "image-driven" not in visual_tendencies:
        visual_tendencies.append("image-driven")

    # ── Content types ────────────────────────────────────────────────────
    content_types = _match_keywords(combined_text, _CONTENT_TYPE_KEYWORDS, max_matches=4)

    # ── Complexity ───────────────────────────────────────────────────────
    lower_text = combined_text.lower()
    ambitious_hits = sum(1 for s in _COMPLEXITY_SIGNALS_AMBITIOUS if s in lower_text)
    simple_hits = sum(1 for s in _COMPLEXITY_SIGNALS_SIMPLE if s in lower_text)
    if ambitious_hits >= 2:
        complexity = "ambitious"
    elif simple_hits >= 2:
        complexity = "simple"
    else:
        complexity = "moderate"

    # ── Notable entities ─────────────────────────────────────────────────
    notable: list[str] = []
    if display_name:
        notable.append(display_name)
    # Extract short project names from evidence
    for ev in project_evidence[:8]:
        short = str(ev).strip()[:60]
        if short and short not in notable:
            notable.append(short)
    notable = notable[:10]

    profile = StructuredIdentityProfile(
        themes=themes,
        tone=tone,
        visual_tendencies=visual_tendencies,
        content_types=content_types,
        complexity=complexity,
        notable_entities=notable,
    )
    _log.debug(
        "structured_identity_profile extracted: themes=%s tone=%s visual=%s complexity=%s",
        themes, tone, visual_tendencies, complexity,
    )
    return profile


# ── Experience Mode Derivation ───────────────────────────────────────────────

# Valid experience_mode values (from SOUL.md)
EXPERIENCE_MODES = frozenset({
    "webgl_3d_portfolio",
    "immersive_spatial_portfolio",
    "immersive_identity_experience",
    "model_centric_experience",
    "flat_standard",
})

# Spatial archetypes that strongly signal immersive/interactive mode.
# Note: "portfolio" is kept here for backwards compatibility in mode detection,
# but the derivation rules distinguish portfolio-IA (webgl_3d_portfolio) from
# identity-led spatial experiences (immersive_identity_experience).
_SPATIAL_ARCHETYPES = {"portfolio", "gallery", "experimental", "story_driven"}

# Archetypes that explicitly want portfolio information architecture (hero/work/about/contact).
_PORTFOLIO_IA_ARCHETYPES = {"portfolio"}


def derive_experience_mode_with_confidence(
    structured_identity: StructuredIdentityProfile,
    *,
    site_archetype: str | None = None,
) -> dict[str, Any]:
    """
    Derive experience_mode with a confidence score from structured identity signals.

    Returns ``{"experience_mode": str, "experience_confidence": float}``.
    Confidence (0.0–1.0) reflects signal strength for the winning rule.

    Key distinction:
    - ``webgl_3d_portfolio``: portfolio information architecture (hero/work/about/contact)
      with 3D/WebGL decoration. Only when site_archetype is explicitly "portfolio" AND
      there is portfolio content (projects, photography, etc.).
    - ``immersive_identity_experience``: spatial/creative experience that is identity-led
      but NOT portfolio-shaped. Use for experimental, gallery, story_driven, or ambitious
      creative identities where the surface should be an experience not a resume.
    - ``immersive_spatial_portfolio``: deepest spatial mode; for very strong spatial signals.
    """
    themes = set(structured_identity.themes)
    visual = set(structured_identity.visual_tendencies)
    content = set(structured_identity.content_types)
    complexity = structured_identity.complexity
    sa = (site_archetype or "").strip().lower()
    is_portfolio_archetype = sa in _PORTFOLIO_IA_ARCHETYPES

    # Rule 1: Explicit spatial visual tendency → most immersive mode
    if "spatial" in visual:
        return {"experience_mode": "immersive_spatial_portfolio", "experience_confidence": 0.9}

    # Rule 2: Ambitious + visual-heavy
    #   → portfolio archetype with portfolio content: webgl_3d_portfolio
    #   → non-portfolio or creative: immersive_identity_experience
    if complexity == "ambitious" and visual & {"image-driven", "motion-heavy"}:
        portfolio_content = content & {"projects", "photography", "design", "art"}
        if is_portfolio_archetype and portfolio_content:
            return {"experience_mode": "webgl_3d_portfolio", "experience_confidence": 0.85}
        return {"experience_mode": "immersive_identity_experience", "experience_confidence": 0.85}

    # Rule 3: Spatial archetype + creative theme signals
    #   → explicitly portfolio archetype: webgl_3d_portfolio (portfolio IA + 3D)
    #   → other spatial archetypes (gallery/experimental/story_driven): identity-led experience
    creative_themes = themes & {"cinematic", "experimental", "artistic"}
    if sa and sa in _SPATIAL_ARCHETYPES and creative_themes:
        if is_portfolio_archetype:
            return {"experience_mode": "webgl_3d_portfolio", "experience_confidence": 0.8}
        return {"experience_mode": "immersive_identity_experience", "experience_confidence": 0.8}

    # Rule 4: Text-heavy with no visual signals → flat
    text_only_content = content <= {"writing"} and content  # writing only, non-empty
    if text_only_content and not visual:
        return {"experience_mode": "flat_standard", "experience_confidence": 0.85}

    # Rule 5: Simple complexity, no spatial/motion → flat
    if complexity == "simple" and not (visual & {"spatial", "motion-heavy", "image-driven"}):
        return {"experience_mode": "flat_standard", "experience_confidence": 0.8}

    # Rule 6a: Moderate+ complexity with portfolio content + visual signals
    #   → only webgl_3d_portfolio when archetype explicitly requests portfolio IA
    portfolio_content = content & {"projects", "photography", "design", "art"}
    if portfolio_content and (visual or creative_themes):
        if is_portfolio_archetype:
            return {"experience_mode": "webgl_3d_portfolio", "experience_confidence": 0.7}
        return {"experience_mode": "immersive_identity_experience", "experience_confidence": 0.7}

    # Rule 6b: Spatial site archetype without strong creative themes
    #   → portfolio archetype: webgl_3d_portfolio
    #   → non-portfolio spatial: immersive_identity_experience
    if sa and sa in _SPATIAL_ARCHETYPES:
        if is_portfolio_archetype:
            return {"experience_mode": "webgl_3d_portfolio", "experience_confidence": 0.65}
        return {"experience_mode": "immersive_identity_experience", "experience_confidence": 0.65}

    # Rule 7: Fallback
    return {"experience_mode": "flat_standard", "experience_confidence": 0.4}


def derive_experience_mode(
    structured_identity: StructuredIdentityProfile,
    *,
    site_archetype: str | None = None,
) -> str:
    """
    Derive experience_mode from structured identity signals.

    Returns one of the canonical experience_mode values. The derivation is
    deterministic and explainable — no hardcoded always-3D behavior.

    Decision logic:
      1. If visual_tendencies include 'spatial' → immersive_spatial_portfolio
      2. If complexity is 'ambitious' + visual heavy:
           - portfolio archetype + portfolio content → webgl_3d_portfolio
           - otherwise → immersive_identity_experience
      3. If site_archetype is spatial + creative themes:
           - portfolio archetype → webgl_3d_portfolio
           - other spatial (gallery/experimental/story_driven) → immersive_identity_experience
      4. If content_types are text-heavy (writing only, no visual) → flat_standard
      5. If complexity is 'simple' and no spatial signals → flat_standard
      6a. Moderate+ complexity with portfolio content + visual signals:
           - portfolio archetype → webgl_3d_portfolio
           - otherwise → immersive_identity_experience
      6b. Spatial site_archetype without creative themes:
           - portfolio archetype → webgl_3d_portfolio
           - otherwise → immersive_identity_experience
      7. Fallback → flat_standard
    """
    result = derive_experience_mode_with_confidence(
        structured_identity, site_archetype=site_archetype,
    )
    return result["experience_mode"]


# ── Weighted Identity Signals ────────────────────────────────────────────────


def compute_weighted_identity_signals(
    profile: StructuredIdentityProfile,
    combined_text: str,
) -> dict[str, Any]:
    """
    Return a weighted version of the identity profile dict.

    Same structure as ``profile.to_dict()`` but ``themes`` entries become
    ``[{"value": str, "weight": float}, ...]`` with weights derived from
    keyword hit counts (normalized to 0.0–1.0 range).  Deterministic.
    """
    base = profile.to_dict()

    theme_hits = _match_keywords_weighted(combined_text, _THEME_KEYWORDS, max_matches=len(_THEME_KEYWORDS))
    if not theme_hits:
        return base

    max_hits = max(count for _, count in theme_hits)
    hit_map = {label: count for label, count in theme_hits}

    if "themes" in base:
        base["themes"] = [
            {
                "value": t,
                "weight": round(hit_map[t] / max_hits, 3) if t in hit_map else 0.0,
            }
            for t in profile.themes
        ]

    return base


# ── Spatial Translation Hints ────────────────────────────────────────────────

_SPATIAL_TRANSLATION_MAP: dict[str, str] = {
    "image-driven": "map projects to 3D planes",
    "motion-heavy": "use animated transitions and camera movement",
    "spatial": "full 3D scene layout with depth and perspective",
    "typography-first": "use text as spatial elements in 3D space",
}


def derive_spatial_translation_hints(visual_tendencies: list[str]) -> list[str]:
    """Deterministic mapping from visual tendencies to spatial translation hints."""
    hints: list[str] = []
    for tendency in visual_tendencies:
        hint = _SPATIAL_TRANSLATION_MAP.get(tendency)
        if hint:
            hints.append(hint)
    return hints
