"""Hydrate planner-facing ``identity_context`` from persisted identity rows (no inference)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from kmbl_orchestrator.domain import IdentityProfileRecord, IdentitySourceRecord
from kmbl_orchestrator.persistence.repository import Repository

DEFAULT_FALLBACK_PROFILE: dict[str, Any] = {
    "profile_summary": "Creative Architect — versatile digital creator with a modern aesthetic sensibility",
    "facets_json": {
        "tone_keywords": ["professional", "innovative", "approachable"],
        "aesthetic_keywords": ["modern", "clean", "balanced"],
    },
}


def _snippet(text: str | None, max_len: int = 200) -> str | None:
    if text is None:
        return None
    t = text.strip()
    if not t:
        return None
    return t if len(t) <= max_len else t[: max_len - 1] + "…"


def build_planner_identity_context(
    repo: Repository, identity_id: UUID | None
) -> dict[str, Any]:
    """Return JSON-serializable dict for ``PlannerRoleInput.identity_context``."""
    if identity_id is None:
        return {}
    profile = repo.get_identity_profile(identity_id)
    sources = repo.list_identity_sources(identity_id)
    recent: list[dict[str, Any]] = []
    for s in sources[:8]:
        recent.append(
            {
                "identity_source_id": str(s.identity_source_id),
                "source_type": s.source_type,
                "summary": _snippet(s.raw_text) or s.source_uri or s.source_type,
            }
        )
    out: dict[str, Any] = {
        "identity_id": str(identity_id),
        "profile_summary": profile.profile_summary if profile else None,
        "facets_json": dict(profile.facets_json) if profile else {},
        "open_questions_json": list(profile.open_questions_json) if profile else [],
        "source_count": len(sources),
        "recent_source_summaries": recent,
    }

    if not out.get("profile_summary") and not out.get("facets_json"):
        out["profile_summary"] = DEFAULT_FALLBACK_PROFILE["profile_summary"]
        out["facets_json"] = DEFAULT_FALLBACK_PROFILE["facets_json"]
        out["is_fallback"] = True

    return out


def persist_identity_from_seed(
    repo: Repository,
    seed: Any,
    identity_id: UUID | None = None,
) -> UUID:
    """
    Create or update identity records from an IdentitySeed.

    Returns the identity_id used (new or provided).
    """
    from kmbl_orchestrator.identity.seed import IdentitySeed

    if not isinstance(seed, IdentitySeed):
        raise TypeError(f"expected IdentitySeed, got {type(seed).__name__}")

    iid = identity_id or uuid4()

    raw_text = seed.to_profile_summary()
    if seed.short_bio:
        raw_text += f"\n\n{seed.short_bio}"
    if seed.headings:
        raw_text += "\n\nHeadings: " + " | ".join(seed.headings[:5])

    source = IdentitySourceRecord(
        identity_source_id=uuid4(),
        identity_id=iid,
        source_type="website_scrape",
        source_uri=seed.source_url,
        raw_text=raw_text[:2000],
        metadata_json={
            "extraction_confidence": seed.confidence,
            "extraction_notes": seed.extraction_notes,
            "tone_keywords": seed.tone_keywords,
            "aesthetic_keywords": seed.aesthetic_keywords,
        },
    )
    repo.create_identity_source(source)

    profile = IdentityProfileRecord(
        identity_id=iid,
        profile_summary=seed.to_profile_summary(),
        facets_json=seed.to_facets_json(),
        open_questions_json=[],
    )
    repo.upsert_identity_profile(profile)

    return iid
