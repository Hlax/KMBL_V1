"""Pass J — review queue action state from persisted staging + publication counts only."""

from __future__ import annotations

from kmbl_orchestrator.domain import StagingSnapshotRecord


def derive_review_action_state(
    rec: StagingSnapshotRecord,
    linked_publication_count: int,
) -> tuple[str, str]:
    """
    Return (review_action_state, review_action_reason).

    ``linked_publication_count`` from ``publication_snapshot`` rows for this staging id.
    """
    if linked_publication_count > 0:
        return (
            "published",
            "Linked publication snapshot exists — canon is downstream of this staging.",
        )
    st = rec.status
    if st == "rejected":
        return (
            "rejected",
            "Staging was rejected — not eligible for approval or publish.",
        )
    if st == "review_ready":
        return (
            "ready_for_review",
            "Staging is review_ready — operator review pending.",
        )
    if st == "approved":
        return (
            "ready_to_publish",
            "Approved — no publication row for this staging id yet.",
        )
    return (
        "not_actionable",
        f"Status is {st!r} — no pending review or publish action.",
    )


def review_action_sort_key(
    review_action_state: str,
    created_at: str | None,
) -> tuple[int, float]:
    """Lower tuple sorts earlier: tier order, then newer ``created_at`` first within tier."""
    from datetime import datetime

    tier = {
        "ready_for_review": 0,
        "ready_to_publish": 1,
        "published": 2,
        "rejected": 3,
        "not_actionable": 4,
    }.get(review_action_state, 9)
    ts = 0.0
    if created_at:
        try:
            ts = datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            ts = 0.0
    return (tier, -ts)
