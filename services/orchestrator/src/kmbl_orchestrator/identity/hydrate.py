"""Hydrate planner-facing ``identity_context`` from persisted identity rows (no inference)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from kmbl_orchestrator.persistence.repository import Repository


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
    return out
