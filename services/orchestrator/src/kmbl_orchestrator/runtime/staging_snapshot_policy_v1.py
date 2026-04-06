"""Deterministic rules for when staging_node persists an immutable staging_snapshot row."""

from __future__ import annotations


def should_create_staging_snapshot(
    policy: str,
    marked_for_review: bool,
    *,
    evaluation_status: str,
    allow_partial_under_always: bool,
) -> bool:
    """Whether to persist a staging_snapshot row (operator-facing review artifact).

    Under ``always``, ``partial`` is excluded by default unless ``allow_partial_under_always`` is set.
    Unknown policy values default to True (do not silently drop rows).
    """
    if policy == "never":
        return False
    if policy == "on_nomination":
        return marked_for_review
    if policy == "always":
        if evaluation_status == "partial" and not allow_partial_under_always:
            return False
        return True
    return True


def staging_snapshot_skip_reason(
    policy: str,
    marked_for_review: bool,
    *,
    evaluation_status: str,
    allow_partial_under_always: bool,
) -> str | None:
    if policy == "never":
        return "policy_never"
    if policy == "on_nomination" and not marked_for_review:
        return "on_nomination_not_marked"
    if (
        policy == "always"
        and evaluation_status == "partial"
        and not allow_partial_under_always
    ):
        return "always_partial_excluded_default"
    return None
