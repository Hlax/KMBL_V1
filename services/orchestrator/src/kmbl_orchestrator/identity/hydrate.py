"""Hydrate planner-facing ``identity_context`` from persisted identity rows (no inference)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from kmbl_orchestrator.domain import IdentityProfileRecord, IdentitySourceRecord
from kmbl_orchestrator.persistence.repository import Repository

if TYPE_CHECKING:
    from kmbl_orchestrator.config import Settings

_log = logging.getLogger(__name__)

# Max evolution signals to retain in identity_profile.facets_json
_MAX_EVOLUTION_SIGNALS = 20

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
    repo: Repository,
    identity_id: UUID | None,
    *,
    settings: "Settings | None" = None,
) -> dict[str, Any]:
    """Return JSON-serializable dict for ``PlannerRoleInput.identity_context``."""
    from kmbl_orchestrator.config import get_settings

    s = settings or get_settings()
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
        if s.identity_allow_fallback_profile:
            out["profile_summary"] = DEFAULT_FALLBACK_PROFILE["profile_summary"]
            out["facets_json"] = DEFAULT_FALLBACK_PROFILE["facets_json"]
            out["is_fallback"] = True
        else:
            out["identity_unresolved"] = True
            out["identity_unresolved_reason"] = "no_profile_or_facets"
            out["facets_json"] = {}

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


def upsert_identity_evolution_signal(
    repo: Repository,
    identity_id: UUID,
    *,
    graph_run_id: UUID,
    evaluation_status: str,
    evaluation_summary: str,
    issue_count: int,
    user_rating: int | None = None,
    user_feedback: str | None = None,
    staging_snapshot_id: UUID | None = None,
) -> None:
    """Upsert a structured evaluation signal into identity_profile.facets_json.

    This closes the evaluator→identity feedback loop so future planner invocations
    receive a richer context reflecting what has/hasn't worked across prior runs.
    Retains the most recent ``_MAX_EVOLUTION_SIGNALS`` entries.
    """
    profile = repo.get_identity_profile(identity_id)
    facets: dict[str, Any] = dict(profile.facets_json) if profile else {}
    signals: list[dict[str, Any]] = list(facets.get("evolution_signals") or [])

    signal: dict[str, Any] = {
        "graph_run_id": str(graph_run_id),
        "evaluation_status": evaluation_status,
        "evaluation_summary": evaluation_summary[:300] if evaluation_summary else "",
        "issue_count": issue_count,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    if user_rating is not None:
        signal["user_rating"] = user_rating
    if user_feedback:
        signal["user_feedback"] = user_feedback[:300]
    if staging_snapshot_id:
        signal["staging_snapshot_id"] = str(staging_snapshot_id)

    signals.append(signal)
    # Retain only the most recent N signals
    signals = signals[-_MAX_EVOLUTION_SIGNALS:]
    facets["evolution_signals"] = signals

    # Derive a simple trend label the planner can use directly
    recent_statuses = [s.get("evaluation_status", "fail") for s in signals[-5:]]
    pass_count = sum(1 for s in recent_statuses if s == "pass")
    partial_count = sum(1 for s in recent_statuses if s == "partial")
    if pass_count >= 2:
        facets["recent_quality_trend"] = "improving"
    elif partial_count >= 3:
        facets["recent_quality_trend"] = "partial_plateau"
    elif recent_statuses.count("fail") >= 3:
        facets["recent_quality_trend"] = "stuck"
    else:
        facets["recent_quality_trend"] = "mixed"

    # Persist recent ratings trend
    recent_ratings = [
        s["user_rating"] for s in signals[-5:] if s.get("user_rating") is not None
    ]
    if recent_ratings:
        facets["recent_user_ratings"] = recent_ratings

    updated_profile = IdentityProfileRecord(
        identity_id=identity_id,
        profile_summary=profile.profile_summary if profile else None,
        facets_json=facets,
        open_questions_json=list(profile.open_questions_json) if profile else [],
    )
    repo.upsert_identity_profile(updated_profile)
    _log.info(
        "identity_evolution_signal upserted identity_id=%s status=%s trend=%s",
        identity_id,
        evaluation_status,
        facets.get("recent_quality_trend", "unknown"),
    )
