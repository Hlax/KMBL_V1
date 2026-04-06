"""Extract evaluator nomination for review snapshot rows from raw kmbl-evaluator JSON."""

from __future__ import annotations

from typing import Any


def extract_evaluator_nomination(
    raw: dict[str, Any] | None,
    *,
    evaluation_status: str | None = None,
) -> dict[str, Any]:
    """
    Return a dict suitable for GraphState ``evaluator_nomination`` and ``StagingSnapshotRecord``.

    Recognized shapes (first match wins for the boolean):
    - Top-level ``nominate_for_review`` or ``marked_for_review`` (bool)
    - ``metrics.nominate_for_review`` or ``metrics.marked_for_review`` (bool)

    Optional:
    - ``mark_reason`` (str) at top level or under ``metrics``
    - ``review_tags`` (list[str]) at top level or under ``metrics``

    When no **explicit** bool nomination is present and ``evaluation_status`` is set:
    - ``pass`` defaults to ``marked_for_review=True`` (operator review / snapshot eligibility)
    - ``partial``, ``fail``, ``blocked`` default to ``marked_for_review=False`` unless the model
      explicitly set a bool (partial stays internal by default).
    """
    if not raw or not isinstance(raw, dict):
        marked = False
        if evaluation_status == "pass":
            marked = True
        elif evaluation_status in ("partial", "fail", "blocked"):
            marked = False
        return {
            "marked_for_review": marked,
            "mark_reason": None,
            "review_tags": [],
        }

    marked = False
    explicit = False
    top_keys = ("nominate_for_review", "marked_for_review")
    top_has_nomination = any(k in raw for k in top_keys)
    if top_has_nomination:
        for key in top_keys:
            v = raw.get(key)
            if isinstance(v, bool):
                explicit = True
                marked = v
                break
    if not explicit:
        metrics = raw.get("metrics")
        if isinstance(metrics, dict):
            for key in top_keys:
                v = metrics.get(key)
                if isinstance(v, bool):
                    explicit = True
                    marked = v
                    break
    if not explicit and evaluation_status is not None:
        if evaluation_status == "pass":
            marked = True
        elif evaluation_status in ("partial", "fail", "blocked"):
            marked = False

    reason: str | None = None
    r = raw.get("mark_reason")
    if isinstance(r, str) and r.strip():
        reason = r.strip()
    else:
        metrics = raw.get("metrics")
        if isinstance(metrics, dict):
            mr = metrics.get("mark_reason")
            if isinstance(mr, str) and mr.strip():
                reason = mr.strip()

    tags: list[str] = []
    rt = raw.get("review_tags")
    if isinstance(rt, list):
        tags = [str(x) for x in rt if isinstance(x, (str, int, float))]
    else:
        metrics = raw.get("metrics")
        rt2 = metrics.get("review_tags") if isinstance(metrics, dict) else None
        if isinstance(rt2, list):
            tags = [str(x) for x in rt2 if isinstance(x, (str, int, float))]

    return {
        "marked_for_review": marked,
        "mark_reason": reason,
        "review_tags": tags,
    }
