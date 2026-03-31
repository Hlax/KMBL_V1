"""Autonomous loop service - runs creative iterations until completion or proposal."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from kmbl_orchestrator.persistence.repository import Repository

from kmbl_orchestrator.domain import AutonomousLoopRecord
from kmbl_orchestrator.identity.extract import extract_identity_from_url
from kmbl_orchestrator.identity.hydrate import persist_identity_from_seed
from kmbl_orchestrator.seeds import build_identity_url_static_frontend_event_input

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
    
    Phases:
    - identity_fetch: Extract identity from URL
    - planning: Invoke planner (via graph)
    - generating: Invoke generator (via graph)
    - evaluating: Invoke evaluator (via graph)
    - proposing: Check if evaluator wants to propose for publication
    - idle: Waiting for next direction or user input
    """
    loop_id = loop.loop_id
    
    try:
        if loop.phase == "identity_fetch":
            return await _tick_identity_fetch(repo, loop)
        
        if loop.phase in ("planning", "generating", "evaluating"):
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
        repo.update_loop_state(loop_id, status="failed")
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
    """Fetch identity from URL and persist."""
    _log.info("Loop %s: fetching identity from %s", loop.loop_id, loop.identity_url)
    
    seed = await extract_identity_from_url(loop.identity_url, deep_crawl=True)
    if seed is None:
        repo.update_loop_state(loop.loop_id, status="failed")
        return LoopTickResult(
            loop_id=loop.loop_id,
            action="identity_fetch_failed",
            phase_after="identity_fetch",
            iteration=0,
            error="Could not extract identity from URL",
        )
    
    identity_id = await persist_identity_from_seed(repo, seed)
    
    repo.update_loop_state(
        loop.loop_id,
        phase="planning",
        status="running",
    )
    
    return LoopTickResult(
        loop_id=loop.loop_id,
        action="identity_fetched",
        phase_after="planning",
        iteration=0,
    )


async def _tick_graph_run(
    repo: "Repository",
    loop: AutonomousLoopRecord,
    *,
    run_graph_fn: Any = None,
) -> LoopTickResult:
    """Run a graph iteration (planner → generator → evaluator)."""
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
        identity_id=loop.identity_id,
    )
    
    try:
        result = await run_graph_fn(
            identity_url=loop.identity_url,
            identity_id=loop.identity_id,
            event_input=event_input,
            thread_id=loop.current_thread_id,
        )
        
        graph_run_id = result.get("graph_run_id")
        thread_id = result.get("thread_id")
        staging_snapshot_id = result.get("staging_snapshot_id")
        evaluator_status = result.get("evaluator_status")
        evaluator_score = result.get("evaluator_score")
        
        staging_count = loop.total_staging_count
        if staging_snapshot_id:
            staging_count += 1
        
        repo.update_loop_state(
            loop.loop_id,
            iteration_count=iteration,
            current_thread_id=UUID(thread_id) if thread_id else None,
            current_graph_run_id=UUID(graph_run_id) if graph_run_id else None,
            last_staging_snapshot_id=UUID(staging_snapshot_id) if staging_snapshot_id else None,
            last_evaluator_status=evaluator_status,
            last_evaluator_score=evaluator_score,
            total_staging_count=staging_count,
            phase="proposing" if evaluator_status == "pass" else "planning",
        )
        
        return LoopTickResult(
            loop_id=loop.loop_id,
            action="graph_iteration_completed",
            phase_after="proposing" if evaluator_status == "pass" else "planning",
            iteration=iteration,
            graph_run_id=UUID(graph_run_id) if graph_run_id else None,
            staging_snapshot_id=UUID(staging_snapshot_id) if staging_snapshot_id else None,
        )
    
    except Exception as e:
        _log.exception("Loop %s graph run failed: %s", loop.loop_id, e)
        repo.update_loop_state(loop.loop_id, phase="planning")
        return LoopTickResult(
            loop_id=loop.loop_id,
            action="graph_iteration_failed",
            phase_after="planning",
            iteration=iteration,
            error=str(e),
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
    
    repo.update_loop_state(loop.loop_id, phase="planning")
    return LoopTickResult(
        loop_id=loop.loop_id,
        action="continuing_iteration",
        phase_after="planning",
        iteration=loop.iteration_count,
    )


async def _tick_idle(
    repo: "Repository",
    loop: AutonomousLoopRecord,
) -> LoopTickResult:
    """
    Idle phase - check if planner has new exploration directions.
    
    If planner suggested new directions and we haven't explored them all,
    pick one and continue iterating.
    """
    directions = loop.exploration_directions or []
    completed = set(d.get("id") for d in (loop.completed_directions or []) if d.get("id"))
    
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
        
        repo.update_loop_state(loop.loop_id, phase="planning")
        return LoopTickResult(
            loop_id=loop.loop_id,
            action="exploring_new_direction",
            phase_after="planning",
            iteration=loop.iteration_count,
        )
    
    next_direction = pending[0]
    new_completed = (loop.completed_directions or []) + [next_direction]
    repo.update_loop_state(
        loop.loop_id,
        completed_directions=new_completed,
        phase="planning",
    )
    
    return LoopTickResult(
        loop_id=loop.loop_id,
        action="exploring_direction",
        phase_after="planning",
        iteration=loop.iteration_count,
    )
