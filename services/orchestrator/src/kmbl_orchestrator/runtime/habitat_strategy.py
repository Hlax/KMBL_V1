"""Orchestrator-enforced habitat strategy (fresh surface vs continue refining)."""

from __future__ import annotations

from typing import Any, Literal

HabitatStrategy = Literal["continue", "fresh_start", "rebuild_informed"]


def normalize_habitat_strategy_token(raw: str | None) -> HabitatStrategy:
    """Map planner free-text tokens to a small orchestrator vocabulary."""
    if not raw or not isinstance(raw, str):
        return "continue"
    x = raw.strip().lower()
    if x in ("fresh_start", "fresh", "reset", "new_surface"):
        return "fresh_start"
    if x in ("rebuild_informed", "rebuild", "informed_rebuild"):
        return "rebuild_informed"
    if x in ("continue", "refine", "iterate"):
        return "continue"
    return "continue"


def effective_habitat_strategy_for_iteration(
    *,
    event_input: dict[str, Any] | None,
    build_spec: dict[str, Any] | None,
    iteration_index: int,
) -> HabitatStrategy:
    """Single source of truth for staging/generator/evaluator behavior.

    - ``kmbl_habitat_session`` from the API/OpenClaw run wins on iteration 0 when ``fresh``:
      user explicitly requested a new live habitat (new thread + empty surface, or cleared surface).
    - Otherwise iteration 0 follows ``build_spec.habitat_strategy`` (planner).
    - Iteration > 0 always follows the *current* build_spec (replan), not the original session flag.
    """
    ei = event_input if isinstance(event_input, dict) else {}
    bs = build_spec if isinstance(build_spec, dict) else {}

    if iteration_index == 0 and ei.get("kmbl_habitat_session") == "fresh":
        return "fresh_start"

    raw = bs.get("habitat_strategy")
    return normalize_habitat_strategy_token(raw if isinstance(raw, str) else None)


def build_spec_with_effective_habitat(
    build_spec: dict[str, Any],
    effective: HabitatStrategy,
) -> dict[str, Any]:
    """Attach orchestrator truth for persistence and downstream roles."""
    out = dict(build_spec)
    out["habitat_strategy"] = effective
    meta = out.setdefault("_kmbl_orchestrator", {})
    if isinstance(meta, dict):
        meta["habitat_strategy_effective"] = effective
    return out
