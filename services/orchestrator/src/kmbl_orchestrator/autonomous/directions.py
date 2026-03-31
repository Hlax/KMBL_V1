"""
ExplorationDirection — typed schema for autonomous loop direction items.

Previously exploration_directions was list[dict[str, Any]] with no schema.
The loop marked them completed without ever changing what the planner was asked to do.

This module defines the typed schema and provides builders that produce
directions that actually translate into different planner invocations.

An ExplorationDirection tells the loop: "on the next graph_cycle, give the planner
THIS specific retry_context so it explores a genuinely different approach."

The orchestrator uses the direction's retry_hint to set retry_context in the
graph state before each graph_cycle. The planner then receives a concrete direction.
"""

from __future__ import annotations

import secrets
from typing import Any, Literal

DirectionType = Literal[
    "refine",           # address specific issues, keep visual approach
    "pivot_layout",     # significantly change layout structure
    "pivot_palette",    # keep content, change color scheme
    "pivot_content",    # keep structure, rewrite copy/sections
    "fresh_start",      # discard everything, restart from identity brief only
]


def make_direction(
    direction_type: DirectionType,
    *,
    rationale: str,
    retry_hint: dict[str, Any] | None = None,
    direction_id: str | None = None,
) -> dict[str, Any]:
    """
    Create a typed exploration direction dict.

    Args:
        direction_type: One of the DirectionType literals.
        rationale: Why this direction — used in planner context.
        retry_hint: Extra planner context for this direction.
                    Will be merged into retry_context in the graph state.
        direction_id: Optional stable ID (generated if not provided).
    """
    return {
        "id": direction_id or secrets.token_hex(8),
        "type": direction_type,
        "rationale": rationale,
        "retry_hint": retry_hint or {},
    }


def build_initial_directions_for_identity(
    *,
    identity_brief: dict[str, Any] | None,
    max_directions: int = 4,
) -> list[dict[str, Any]]:
    """
    Build an initial set of exploration directions for an identity loop.

    These are not random — they represent a deliberate coverage of the identity
    space from different angles: layout, palette, content emphasis, tone.

    Each direction produces a different planner invocation shape.
    The loop processes them in order; alignment scores determine when to stop early.
    """
    brief = identity_brief or {}
    display_name = brief.get("display_name") or "the identity"
    tone = ", ".join(brief.get("tone_keywords") or ["professional"])
    palette = ", ".join(brief.get("palette_hex") or [])[:60]
    must_mention = brief.get("must_mention") or []

    directions: list[dict[str, Any]] = [
        make_direction(
            "pivot_layout",
            rationale=(
                f"First iteration: establish primary layout for {display_name}. "
                f"Tone: {tone}. Try portfolio/personal layout with clear identity sections."
            ),
            retry_hint={
                "layout_approach": "portfolio_personal",
                "must_include_sections": ["hero", "about", "work"],
                "tone_directive": tone,
            },
            direction_id="dir_layout_1",
        ),
        make_direction(
            "pivot_palette",
            rationale=(
                f"Second iteration: emphasize palette identity for {display_name}. "
                f"Colors from source: {palette or 'derive from tone'}. "
                "Keep layout, change color scheme to match identity palette."
            ),
            retry_hint={
                "palette_directive": "strictly use palette_hex from identity_brief",
                "palette_colors": brief.get("palette_hex") or [],
                "keep_layout": True,
            },
            direction_id="dir_palette_2",
        ),
        make_direction(
            "pivot_content",
            rationale=(
                f"Third iteration: maximize content alignment for {display_name}. "
                f"Must include: {must_mention[:3]}. "
                "Keep structure, rewrite copy to maximize must_mention hit rate."
            ),
            retry_hint={
                "content_directive": "maximize must_mention presence",
                "must_mention": must_mention,
                "keep_layout": True,
                "keep_palette": True,
            },
            direction_id="dir_content_3",
        ),
        make_direction(
            "refine",
            rationale=(
                f"Fourth iteration: refine based on best prior output for {display_name}. "
                "Address specific issues from best-scoring prior run."
            ),
            retry_hint={
                "strategy": "refine_best_prior",
                "note": "Use identity_brief constraints strictly. Address all alignment_report misses.",
            },
            direction_id="dir_refine_4",
        ),
    ]

    return directions[:max_directions]


def direction_to_retry_context(
    direction: dict[str, Any],
    *,
    iteration_index: int,
    prior_alignment_score: float | None = None,
) -> dict[str, Any]:
    """
    Convert a direction dict into a retry_context for the graph state.

    This is the bridge between the autonomous loop's direction queue
    and the graph's retry_context mechanism.
    """
    retry_hint = dict(direction.get("retry_hint") or {})
    return {
        "retry_direction": direction.get("type", "refine"),
        "iteration_strategy": direction.get("type", "refine"),
        "direction_id": direction.get("id"),
        "rationale": direction.get("rationale", ""),
        "prior_alignment_score": prior_alignment_score,
        "iteration_index": iteration_index,
        "orchestrator_note": (
            f"Direction from autonomous loop: {direction.get('type')}. "
            f"Rationale: {direction.get('rationale', '')}. "
            "This is a binding orchestrator direction."
        ),
        **retry_hint,
    }


def validate_direction(d: Any) -> bool:
    """Return True if d is a valid exploration direction dict."""
    if not isinstance(d, dict):
        return False
    if "id" not in d or not isinstance(d.get("id"), str):
        return False
    if d.get("type") not in (
        "refine", "pivot_layout", "pivot_palette", "pivot_content", "fresh_start"
    ):
        return False
    return True
