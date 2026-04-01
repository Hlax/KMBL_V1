"""decision_router node — route based on evaluation (iterate, stage, or end)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from kmbl_orchestrator.graph.helpers import (
    compute_evaluator_decision,
    maybe_suppress_duplicate_staging,
)
from kmbl_orchestrator.graph.state import GraphState
from kmbl_orchestrator.identity.alignment import (
    compute_alignment_trend,
    select_retry_direction,
)
from kmbl_orchestrator.runtime.interrupt_checks import raise_if_interrupt_requested
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event

if TYPE_CHECKING:
    from kmbl_orchestrator.graph.app import GraphContext

_log = logging.getLogger(__name__)


def decision_router(ctx: "GraphContext", state: GraphState) -> dict[str, Any]:
    """Decide whether to iterate, stage, or end based on the evaluation report."""
    gid = UUID(state["graph_run_id"])
    raise_if_interrupt_requested(
        ctx.repo, gid, UUID(state["thread_id"])
    )
    ev = state.get("evaluation_report") or {}
    status = ev.get("status", "fail")
    iteration = int(state.get("iteration_index", 0))
    max_iter = int(state.get("max_iterations", ctx.settings.graph_max_iterations_default))

    decision, interrupt_reason = compute_evaluator_decision(
        status, iteration, max_iter
    )

    metrics = ev.get("metrics") if isinstance(ev.get("metrics"), dict) else {}
    decision, interrupt_reason, dup_suppressed = maybe_suppress_duplicate_staging(
        decision, interrupt_reason, status, metrics
    )
    if dup_suppressed:
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.CONTRACT_WARNING,
            {
                "kind": "duplicate_staging_suppressed",
                "message": "Evaluation still duplicate vs prior staging; skipping snapshot",
            },
            thread_id=UUID(state["thread_id"]),
        )

    if status not in ("pass", "partial"):
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.STAGING_SNAPSHOT_BLOCKED,
            {
                "reason": "evaluator_not_pass",
                "error_kind": "staging_integrity",
                "evaluation_status": status,
            },
        )

    out: dict[str, Any] = {"decision": decision}
    if interrupt_reason:
        out["interrupt_reason"] = interrupt_reason

    # Track pass_count for quality-based visibility (currently informational;
    # enables future policy: "require N consecutive passes before staging").
    current_pass_count = int(state.get("pass_count") or 0)
    if status == "pass":
        out["pass_count"] = current_pass_count + 1
    else:
        out["pass_count"] = 0

    # Fix 3: compute retry_direction and retry_context for next iteration.
    # This is orchestrator-owned — the planner receives a concrete direction,
    # not just a request to "do better." The direction is deterministic from
    # alignment trend + evaluator status + stagnation.
    if decision == "iterate":
        next_iteration = iteration + 1
        out["iteration_index"] = next_iteration

        alignment_score: float | None = state.get("last_alignment_score")
        alignment_history: list[dict[str, Any]] = list(
            state.get("alignment_score_history") or []
        )
        alignment_trend = compute_alignment_trend(alignment_history)
        stagnation = int(
            (state.get("current_state") or {}).get("stagnation_count", 0)
        )
        prior_direction: str | None = state.get("retry_direction")

        retry_dir = select_retry_direction(
            alignment_score=alignment_score,
            alignment_trend=alignment_trend,
            evaluator_status=status,
            iteration_index=iteration,
            stagnation_count=stagnation,
            prior_direction=prior_direction,
        )
        out["retry_direction"] = retry_dir

        # Extract failed criteria IDs from issues for planner context
        issues = ev.get("issues") or []
        failed_criteria = [
            iss.get("type") or iss.get("id") or iss.get("criterion")
            for iss in issues
            if isinstance(iss, dict)
        ]
        failed_criteria = [f for f in failed_criteria if f][:8]

        retry_context: dict[str, Any] = {
            "retry_direction": retry_dir,
            "iteration_strategy": retry_dir,  # mirrors iteration_plan key
            "prior_alignment_score": alignment_score,
            "alignment_trend": alignment_trend,
            "failed_criteria_ids": failed_criteria,
            "iteration_index": next_iteration,
            "orchestrator_note": (
                f"Direction selected by orchestrator based on alignment_trend={alignment_trend} "
                f"status={status} iteration={iteration}. "
                f"This is binding — use {retry_dir} strategy."
            ),
        }
        out["retry_context"] = retry_context

        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.ITERATION_STARTED,
            {
                "iteration_index": next_iteration,
                "previous_status": status,
                "max_iterations": max_iter,
                "retry_direction": retry_dir,
                "alignment_score": alignment_score,
                "alignment_trend": alignment_trend,
            },
        )
    append_graph_run_event(
        ctx.repo,
        gid,
        RunEventType.DECISION_MADE,
        {
            "decision": decision,
            "interrupt_reason": interrupt_reason,
            "pass_count": out["pass_count"],
            "evaluation_status": status,
            "retry_direction": out.get("retry_direction"),
            "last_alignment_score": state.get("last_alignment_score"),
        },
    )
    return out
