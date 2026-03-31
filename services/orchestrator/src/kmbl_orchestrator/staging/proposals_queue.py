"""Proposals queue — filtering and sorting for staging snapshot proposals list."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.staging.review_action import review_action_sort_key

MAX_REPO_FETCH = 500

ALLOWED_REVIEW_ACTION_STATES: frozenset[str] = frozenset(
    {
        "published",
        "ready_for_review",
        "ready_to_publish",
        "not_actionable",
    }
)


def normalize_blank(s: str | None) -> str | None:
    if s is None:
        return None
    t = s.strip()
    return None if t == "" else t


def parse_has_publication(s: str | None) -> bool | None:
    """Tri-state: None = no filter; True/False = filter by linked publication presence."""
    n = normalize_blank(s)
    if n is None:
        return None
    v = n.lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    return None


def parse_sort_mode(s: str | None) -> str:
    n = normalize_blank(s)
    if n is None:
        return "default"
    v = n.lower()
    if v in ("default", "newest", "oldest"):
        return v
    return "default"


def validate_review_action_state(s: str | None) -> str | None:
    n = normalize_blank(s)
    if n is None:
        return None
    if n not in ALLOWED_REVIEW_ACTION_STATES:
        raise ValueError(f"invalid review_action_state: {n!r}")
    return n


def use_wide_pool(
    *,
    review_action_state: str | None,
    has_publication: bool | None,
    sort_mode: str,
) -> bool:
    if review_action_state is not None:
        return True
    if has_publication is not None:
        return True
    if sort_mode != "default":
        return True
    return False


def fetch_limit(*, limit: int, wide: bool) -> int:
    lim = max(1, min(limit, MAX_REPO_FETCH))
    if wide:
        return min(MAX_REPO_FETCH, max(lim, 100))
    return lim


def filter_proposals(
    proposals: list[dict[str, Any]],
    *,
    review_action_state: str | None,
    has_publication: bool | None,
) -> list[dict[str, Any]]:
    out = proposals
    if review_action_state is not None:
        out = [p for p in out if p["review_action_state"] == review_action_state]
    if has_publication is not None:
        if has_publication:
            out = [p for p in out if p["linked_publication_count"] > 0]
        else:
            out = [p for p in out if p["linked_publication_count"] == 0]
    return out


def _ts(created_at: str | None) -> float:
    from datetime import datetime

    if not created_at:
        return 0.0
    try:
        return datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def sort_proposals_in_place(proposals: list[dict[str, Any]], *, sort_mode: str) -> None:
    if sort_mode == "default":
        proposals.sort(
            key=lambda x: review_action_sort_key(
                x["review_action_state"],
                x.get("created_at"),
            )
        )
    elif sort_mode == "newest":
        proposals.sort(
            key=lambda x: (
                -_ts(x.get("created_at")),
                str(x.get("staging_snapshot_id", "")),
            ),
        )
    else:
        proposals.sort(
            key=lambda x: (
                _ts(x.get("created_at")),
                str(x.get("staging_snapshot_id", "")),
            ),
        )
