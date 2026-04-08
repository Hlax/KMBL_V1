"""decision_router node — route based on evaluation (iterate, stage, or end)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from kmbl_orchestrator.graph.helpers import (
    apply_mixed_lane_failure_policy,
    compute_evaluator_decision,
    maybe_suppress_duplicate_staging,
)
from kmbl_orchestrator.runtime.demo_preview_grounding import is_grounding_only_partial
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
    if not isinstance(ev, dict) or "status" not in ev:
        _log.warning(
            "decision_router graph_run_id=%s evaluation_report missing or malformed, defaulting to fail",
            gid,
        )
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.CONTRACT_WARNING,
            {
                "kind": "missing_evaluation_report",
                "message": "evaluation_report missing or has no status field; defaulting to fail",
            },
            thread_id=UUID(state["thread_id"]),
        )
    status = ev.get("status", "fail") if isinstance(ev, dict) else "fail"
    iteration = int(state.get("iteration_index", 0))
    max_iter = int(state.get("max_iterations", ctx.settings.graph_max_iterations_default))

    decision, interrupt_reason = compute_evaluator_decision(
        status, iteration, max_iter
    )

    metrics = ev.get("metrics") if isinstance(ev.get("metrics"), dict) else {}
    decision, interrupt_reason, dup_suppressed = maybe_suppress_duplicate_staging(
        decision, interrupt_reason, status, metrics
    )

    issues_for_policy = ev.get("issues") if isinstance(ev.get("issues"), list) else []
    stagnation_now = int((state.get("current_state") or {}).get("stagnation_count", 0))
    decision, interrupt_reason, mixed_lane_policy = apply_mixed_lane_failure_policy(
        decision,
        interrupt_reason,
        status=status,
        iteration=iteration,
        max_iterations=max_iter,
        issues=issues_for_policy,
        metrics=metrics,
        stagnation_count=stagnation_now,
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

    # ── Grounding-only partial override ────────────────────────────────────
    # When the evaluator was pass on all quality criteria but downgraded to
    # partial solely because demo preview grounding could not be verified,
    # generator iteration is wasteful — the build is already acceptable.
    # Reroute iterate → stage (degraded) so the output is surfaced to the
    # operator rather than wasting a generator call on an infra gap.
    if decision == "iterate" and is_grounding_only_partial(metrics):
        decision = "stage"
        _log.info(
            "decision_router graph_run_id=%s grounding_only_partial=True "
            "rerouting iterate→stage (build quality was pass; infra gap cannot be fixed by generator)",
            gid,
        )
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.DEGRADED_STAGING,
            {
                "message": (
                    "Grounding-only partial: build quality was acceptable (evaluator passed all "
                    "quality criteria) but demo preview grounding was not satisfied. "
                    "Routing to stage (degraded) rather than generator retry — the generator "
                    "cannot fix a preview infrastructure gap."
                ),
                "evaluation_status": status,
                "grounding_only_partial": True,
                "iteration_index": iteration,
                "preview_grounding_fallback_reason": metrics.get("preview_grounding_fallback_reason"),
            },
            thread_id=UUID(state["thread_id"]),
        )

    # ── Weakly-grounded retry cap ─────────────────────────────────────────
    # When the evaluator ran without browser-reachable preview (artifact-only),
    # further retries beyond a configurable cap are unlikely to improve quality
    # because feedback is based on weak grounding.  Cap retries to avoid token
    # waste in local-dev / non-tunnel environments.
    weak_cap = int(getattr(ctx.settings, "kmbl_weakly_grounded_max_iterations", 0))
    if decision == "iterate" and weak_cap > 0:
        grounding_mode = str(metrics.get("preview_grounding_mode") or "").strip()
        # "browser" (from normalized mode) or "browser_reachable" (raw resolution value)
        # both indicate actual browser access.  Everything else is weak.
        weakly_grounded = grounding_mode not in ("browser", "browser_reachable")
        if weakly_grounded and iteration >= weak_cap:
            decision = "stage"
            _log.info(
                "decision_router graph_run_id=%s weakly_grounded_retry_cap "
                "iteration=%d cap=%d grounding_mode=%s "
                "rerouting iterate→stage (artifact-only evaluation cap reached)",
                gid,
                iteration,
                weak_cap,
                grounding_mode,
            )
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.WEAKLY_GROUNDED_RETRY_CAP,
                {
                    "message": (
                        f"Weakly-grounded retry cap reached: iteration {iteration} >= cap {weak_cap}. "
                        f"Evaluator grounding mode is '{grounding_mode}' (not browser-reachable). "
                        "Routing to stage (degraded) to avoid token waste on artifact-only feedback loops. "
                        "Provide a browser-reachable preview via KMBL_ORCHESTRATOR_PUBLIC_BASE_URL or a public build_candidate preview URL, "
                        "or increase KMBL_WEAKLY_GROUNDED_MAX_ITERATIONS if more retries are needed."
                    ),
                    "evaluation_status": status,
                    "iteration_index": iteration,
                    "weakly_grounded_max_iterations": weak_cap,
                    "preview_grounding_mode": grounding_mode,
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

    # Emit explicit warning when a non-passing evaluation reaches staging at max iterations.
    # This is the degraded-success path: the evaluator said "fail" or "partial" but we
    # exhausted iterations, so we stage anyway.  Operators must be able to see this.
    if decision == "stage" and status in ("fail", "partial"):
        alignment_score_val: float | None = state.get("last_alignment_score")
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.DEGRADED_STAGING,
            {
                "message": (
                    f"Staging with evaluator status '{status}' after {iteration} iteration(s) "
                    f"(max_iterations={max_iter}). Output may not meet quality bar."
                ),
                "evaluation_status": status,
                "iteration_index": iteration,
                "max_iterations": max_iter,
                "last_alignment_score": alignment_score_val,
            },
            thread_id=UUID(state["thread_id"]),
        )

    out: dict[str, Any] = {"decision": decision}
    if interrupt_reason:
        out["interrupt_reason"] = interrupt_reason
    out["mixed_lane_failure_policy_v1"] = mixed_lane_policy

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
        if mixed_lane_policy.get("pivot_required"):
            retry_dir = "pivot_content"
        out["retry_direction"] = retry_dir

        if alignment_score is None:
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.CONTRACT_WARNING,
                {
                    "kind": "alignment_score_unavailable",
                    "retry_direction": retry_dir,
                    "message": "alignment score unavailable; retry direction based on heuristics only",
                },
                thread_id=UUID(state["thread_id"]),
            )

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
            "mixed_lane_failure_policy_v1": mixed_lane_policy,
        },
    )
    return out
