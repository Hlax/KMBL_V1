"""Autonomous loop service — one URL → identity → repeated LangGraph runs until done or proposal."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from kmbl_orchestrator.persistence.repository import Repository

from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.domain import AutonomousLoopRecord
from kmbl_orchestrator.identity.extract import extract_identity_from_url
from kmbl_orchestrator.identity.hydrate import persist_identity_from_seed
from kmbl_orchestrator.seeds import build_identity_url_static_frontend_event_input
from kmbl_orchestrator.autonomous.directions import (
    build_initial_directions_for_identity,
    direction_to_retry_context,
    validate_direction,
)

_log = logging.getLogger(__name__)


class LoopTickResult:
    """Result of a single loop tick."""

    def __init__(
        self,
        *,
        loop_id: UUID,
        action: str,
        phase_after: str,
        iteration: int,
        graph_run_id: UUID | None = None,
        staging_snapshot_id: UUID | None = None,
        proposed: bool = False,
        completed: bool = False,
        error: str | None = None,
    ):
        self.loop_id = loop_id
        self.action = action
        self.phase_after = phase_after
        self.iteration = iteration
        self.graph_run_id = graph_run_id
        self.staging_snapshot_id = staging_snapshot_id
        self.proposed = proposed
        self.completed = completed
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "loop_id": str(self.loop_id),
            "action": self.action,
            "phase_after": self.phase_after,
            "iteration": self.iteration,
            "graph_run_id": str(self.graph_run_id) if self.graph_run_id else None,
            "staging_snapshot_id": str(self.staging_snapshot_id) if self.staging_snapshot_id else None,
            "proposed": self.proposed,
            "completed": self.completed,
            "error": self.error,
        }


def start_autonomous_loop(
    repo: "Repository",
    identity_url: str,
    *,
    max_iterations: int = 50,
    auto_publish_threshold: float = 0.85,
) -> AutonomousLoopRecord:
    """Start a new autonomous loop for an identity URL."""
    identity_id = uuid4()
    loop = AutonomousLoopRecord(
        loop_id=uuid4(),
        identity_id=identity_id,
        identity_url=identity_url,
        status="pending",
        phase="identity_fetch",
        max_iterations=max_iterations,
        auto_publish_threshold=auto_publish_threshold,
    )
    repo.save_autonomous_loop(loop)
    _log.info("Started autonomous loop %s for %s", loop.loop_id, identity_url)
    return loop


async def tick_loop(
    repo: "Repository",
    loop: AutonomousLoopRecord,
    *,
    run_graph_fn: Any = None,
) -> LoopTickResult:
    """
    Execute one tick of the autonomous loop.

    Phases (one graph invocation = ``graph_cycle`` per tick, not separate planner/generator/evaluator phases):
    - identity_fetch: extract identity from URL and persist under ``loop.identity_id``
    - graph_cycle: run full LangGraph (planner → generator → evaluator → decision → staging)
    - proposing: decide auto-publish vs continue
    - idle: optional exploration / completion
    """
    loop_id = loop.loop_id

    try:
        if loop.phase == "identity_fetch":
            return await _tick_identity_fetch(repo, loop)

        if loop.phase == "graph_cycle":
            return await _tick_graph_run(repo, loop, run_graph_fn=run_graph_fn)

        if loop.phase == "proposing":
            return await _tick_proposing(repo, loop)

        if loop.phase == "idle":
            return await _tick_idle(repo, loop)

        return LoopTickResult(
            loop_id=loop_id,
            action="unknown_phase",
            phase_after=loop.phase,
            iteration=loop.iteration_count,
            error=f"Unknown phase: {loop.phase}",
        )

    except Exception as e:
        _log.exception("Loop %s tick failed: %s", loop_id, e)
        repo.update_loop_state(
            loop_id,
            status="failed",
            last_error=str(e)[:2000],
        )
        return LoopTickResult(
            loop_id=loop_id,
            action="error",
            phase_after=loop.phase,
            iteration=loop.iteration_count,
            error=str(e),
        )


async def _tick_identity_fetch(
    repo: "Repository",
    loop: AutonomousLoopRecord,
) -> LoopTickResult:
    """Fetch identity from URL and persist under the loop's pre-assigned ``identity_id``."""
    settings = get_settings()
    _log.info("Loop %s: fetching identity from %s", loop.loop_id, loop.identity_url)

    seed = await asyncio.to_thread(
        lambda: extract_identity_from_url(loop.identity_url, deep_crawl=True),
    )

    if (
        settings.identity_minimum_confidence > 0
        and float(seed.confidence) < settings.identity_minimum_confidence
    ):
        msg = (
            f"identity confidence {seed.confidence:.3f} below "
            f"identity_minimum_confidence {settings.identity_minimum_confidence}"
        )
        repo.update_loop_state(
            loop.loop_id,
            status="failed",
            phase="identity_fetch",
            last_error=msg,
        )
        return LoopTickResult(
            loop_id=loop.loop_id,
            action="identity_fetch_failed",
            phase_after="identity_fetch",
            iteration=0,
            error=msg,
        )

    persist_identity_from_seed(repo, seed, identity_id=loop.identity_id)

    # Build initial typed exploration directions from the identity brief.
    # This replaces the previous untyped list[dict] with no schema.
    from kmbl_orchestrator.identity.brief import build_identity_brief_from_repo
    brief = build_identity_brief_from_repo(repo, loop.identity_id)
    initial_directions = build_initial_directions_for_identity(
        identity_brief=brief.to_generator_payload() if brief else None,
    )

    repo.update_loop_state(
        loop.loop_id,
        phase="graph_cycle",
        status="running",
        reset_loop_error=True,
        exploration_directions=initial_directions,
    )

    return LoopTickResult(
        loop_id=loop.loop_id,
        action="identity_fetched",
        phase_after="graph_cycle",
        iteration=0,
    )


async def _tick_graph_run(
    repo: "Repository",
    loop: AutonomousLoopRecord,
    *,
    run_graph_fn: Any = None,
) -> LoopTickResult:
    """Run one full graph (single LangGraph invocation)."""
    settings = get_settings()
    if run_graph_fn is None:
        return LoopTickResult(
            loop_id=loop.loop_id,
            action="no_graph_runner",
            phase_after=loop.phase,
            iteration=loop.iteration_count,
            error="No graph runner provided",
        )

    iteration = loop.iteration_count + 1

    if iteration > loop.max_iterations:
        repo.update_loop_state(loop.loop_id, status="completed", phase="idle")
        return LoopTickResult(
            loop_id=loop.loop_id,
            action="max_iterations_reached",
            phase_after="idle",
            iteration=iteration,
            completed=True,
        )

    _log.info("Loop %s: starting graph iteration %d", loop.loop_id, iteration)

    event_input = build_identity_url_static_frontend_event_input(
        identity_url=loop.identity_url,
    )

    # Determine retry_context from current pending direction (if any).
    # The direction queue is processed in order; the orchestrator picks the
    # first pending direction and translates it into a retry_context for the graph.
    directions = loop.exploration_directions or []
    completed_ids = {d.get("id") for d in (loop.completed_directions or []) if d.get("id")}
    pending = [d for d in directions if validate_direction(d) and d.get("id") not in completed_ids]
    current_direction = pending[0] if pending else None

    retry_context: dict[str, Any] | None = None
    if current_direction and iteration > 1:
        # iteration 1 = fresh start (no retry_context); subsequent iterations use directions
        retry_context = direction_to_retry_context(
            current_direction,
            iteration_index=iteration,
            prior_alignment_score=loop.last_alignment_score,
        )
        _log.info(
            "Loop %s: applying direction_id=%s type=%s for iteration %d",
            loop.loop_id,
            current_direction.get("id"),
            current_direction.get("type"),
            iteration,
        )

    try:
        result = await run_graph_fn(
            identity_url=loop.identity_url,
            identity_id=loop.identity_id,
            event_input=event_input,
            thread_id=loop.current_thread_id,
            retry_context=retry_context,
        )

        graph_run_id = result.get("graph_run_id")
        thread_id = result.get("thread_id")
        staging_snapshot_id = result.get("staging_snapshot_id")
        evaluator_status = result.get("evaluator_status")
        # alignment_score is now returned from run_graph_fn (graph final state)
        alignment_score: float | None = result.get("last_alignment_score")
        # last_evaluator_score is alignment_score when present, else None
        evaluator_score = alignment_score  # this is the real score now

        staging_count = loop.total_staging_count
        if staging_snapshot_id:
            staging_count += 1

        # Mark the current direction as completed if alignment improved
        # or if we've run at least one graph_cycle for this direction.
        updated_completed = list(loop.completed_directions or [])
        if current_direction:
            prior_score = loop.last_alignment_score or 0.0
            current_score = alignment_score or 0.0
            # Mark direction complete when: alignment improved, or evaluator pass
            if evaluator_status == "pass" or (
                alignment_score is not None and current_score >= prior_score + 0.05
            ):
                updated_completed.append(current_direction)
                _log.info(
                    "Loop %s: direction %s marked complete (alignment %.3f → %.3f)",
                    loop.loop_id,
                    current_direction.get("id"),
                    prior_score,
                    current_score,
                )

        repo.update_loop_state(
            loop.loop_id,
            iteration_count=iteration,
            current_thread_id=UUID(thread_id) if thread_id else None,
            current_graph_run_id=UUID(graph_run_id) if graph_run_id else None,
            last_staging_snapshot_id=UUID(staging_snapshot_id) if staging_snapshot_id else None,
            last_evaluator_status=evaluator_status,
            last_evaluator_score=evaluator_score,
            last_alignment_score=alignment_score,
            total_staging_count=staging_count,
            completed_directions=updated_completed if updated_completed != list(loop.completed_directions or []) else None,
            phase="proposing" if evaluator_status == "pass" else "graph_cycle",
            reset_loop_error=True,
        )

        return LoopTickResult(
            loop_id=loop.loop_id,
            action="graph_iteration_completed",
            phase_after="proposing" if evaluator_status == "pass" else "graph_cycle",
            iteration=iteration,
            graph_run_id=UUID(graph_run_id) if graph_run_id else None,
            staging_snapshot_id=UUID(staging_snapshot_id) if staging_snapshot_id else None,
        )

    except Exception as e:
        _log.exception("Loop %s graph run failed: %s", loop.loop_id, e)
        new_fail = (loop.consecutive_graph_failures or 0) + 1
        err_msg = str(e)[:2000]
        max_c = settings.autonomous_loop_max_consecutive_failures

        if new_fail >= max_c:
            repo.update_loop_state(
                loop.loop_id,
                phase="graph_cycle",
                status="failed",
                last_error=err_msg,
                consecutive_graph_failures=new_fail,
            )
        else:
            repo.update_loop_state(
                loop.loop_id,
                phase="graph_cycle",
                last_error=err_msg,
                consecutive_graph_failures=new_fail,
            )

        return LoopTickResult(
            loop_id=loop.loop_id,
            action="graph_iteration_failed",
            phase_after="graph_cycle",
            iteration=iteration,
            error=err_msg,
        )


async def _tick_proposing(
    repo: "Repository",
    loop: AutonomousLoopRecord,
) -> LoopTickResult:
    """Check if we should propose this build for publication."""
    score = loop.last_evaluator_score or 0.0

    if score >= loop.auto_publish_threshold and loop.last_staging_snapshot_id:
        _log.info(
            "Loop %s: proposing staging %s for publication (score %.2f >= %.2f)",
            loop.loop_id,
            loop.last_staging_snapshot_id,
            score,
            loop.auto_publish_threshold,
        )

        repo.update_loop_state(
            loop.loop_id,
            proposed_staging_id=loop.last_staging_snapshot_id,
            phase="idle",
        )

        return LoopTickResult(
            loop_id=loop.loop_id,
            action="proposed_for_publication",
            phase_after="idle",
            iteration=loop.iteration_count,
            staging_snapshot_id=loop.last_staging_snapshot_id,
            proposed=True,
        )

    repo.update_loop_state(loop.loop_id, phase="graph_cycle")
    return LoopTickResult(
        loop_id=loop.loop_id,
        action="continuing_iteration",
        phase_after="graph_cycle",
        iteration=loop.iteration_count,
    )


async def _tick_idle(
    repo: "Repository",
    loop: AutonomousLoopRecord,
) -> LoopTickResult:
    """Idle — exploration directions or completion when nothing pending."""
    directions = loop.exploration_directions or []
    completed = {d.get("id") for d in (loop.completed_directions or []) if d.get("id")}

    pending = [d for d in directions if d.get("id") not in completed]

    if not pending:
        if loop.iteration_count >= loop.max_iterations:
            repo.update_loop_state(loop.loop_id, status="completed")
            return LoopTickResult(
                loop_id=loop.loop_id,
                action="completed",
                phase_after="idle",
                iteration=loop.iteration_count,
                completed=True,
            )

        repo.update_loop_state(loop.loop_id, phase="graph_cycle")
        return LoopTickResult(
            loop_id=loop.loop_id,
            action="exploring_new_direction",
            phase_after="graph_cycle",
            iteration=loop.iteration_count,
        )

    next_direction = pending[0]
    new_completed = (loop.completed_directions or []) + [next_direction]
    repo.update_loop_state(
        loop.loop_id,
        completed_directions=new_completed,
        phase="graph_cycle",
    )

    return LoopTickResult(
        loop_id=loop.loop_id,
        action="exploring_direction",
        phase_after="graph_cycle",
        iteration=loop.iteration_count,
    )
