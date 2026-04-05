"""
Autonomous loop and cron routes.

Extracted from api/main.py so that the loop execution bridge is a named,
inspectable top-level function rather than a closure buried in a route handler.
The critical bug fix (retry_context forwarding) lives in _run_graph_for_loop below.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker

_log = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class StartLoopBody(BaseModel):
    identity_url: str = Field(..., description="URL to start autonomous iteration on")
    max_iterations: int = Field(default=50, ge=1, le=500)
    auto_publish_threshold: float = Field(default=0.85, ge=0.0, le=1.0)


class LoopResponse(BaseModel):
    loop_id: str
    identity_id: str
    identity_url: str
    status: str
    phase: str
    iteration_count: int
    proposed_staging_id: str | None = None


class InterruptBody(BaseModel):
    message: str = Field(..., description="Instruction to send to the planner")


# ---------------------------------------------------------------------------
# Loop execution bridge — named function for visibility and testability
# ---------------------------------------------------------------------------

async def run_graph_for_loop(
    *,
    repo: Repository,
    settings: Settings,
    identity_url: str,
    identity_id: UUID,
    event_input: dict[str, Any],
    thread_id: UUID | None = None,
    retry_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Async bridge from the autonomous loop tick to ``run_graph``.

    Wraps the synchronous ``run_graph`` call in a thread-pool executor so the
    event loop stays responsive during cron ticks.

    Returns the dict shape expected by ``tick_loop._tick_graph_run``:
        graph_run_id, thread_id, staging_snapshot_id,
        evaluator_status, evaluator_score, last_alignment_score,
        build_spec, build_spec_id.

    ``retry_context`` is forwarded into graph initial state so the
    decision_router's direction selection actually reaches the generator.
    Without this parameter, cross-run direction application is inert.
    """
    t_str, gid_str = persist_graph_run_start(
        repo,
        thread_id=str(thread_id) if thread_id else None,
        graph_run_id=None,
        identity_id=str(identity_id),
        trigger_type="autonomous_loop",
        event_input=event_input,
    )

    initial: dict[str, Any] = {
        "thread_id": t_str,
        "graph_run_id": gid_str,
        "identity_id": str(identity_id),
        "trigger_type": "autonomous_loop",
        "event_input": event_input,
        "max_iterations": settings.graph_max_iterations_default,
    }
    if retry_context:
        initial["retry_context"] = retry_context

    invoker = DefaultRoleInvoker(settings=settings)

    def _sync_run() -> dict[str, Any]:
        final = run_graph(repo=repo, invoker=invoker, settings=settings, initial=initial)
        ev = final.get("evaluation_report") or {}
        ev_status = ev.get("status") if isinstance(ev, dict) else None
        # alignment_score is the canonical improvement signal, not evaluator_confidence.
        alignment_score: float | None = final.get("last_alignment_score")
        return {
            "graph_run_id": final.get("graph_run_id"),
            "thread_id": final.get("thread_id"),
            "staging_snapshot_id": final.get("staging_snapshot_id"),
            "evaluator_status": ev_status,
            "evaluator_score": alignment_score,
            "last_alignment_score": alignment_score,
            # Pass build_spec + id through so the crawl feedback loop can
            # extract URLs the planner actually referenced (grounded crawl).
            "build_spec": final.get("build_spec"),
            "build_spec_id": final.get("build_spec_id"),
        }

    loop_ev = asyncio.get_event_loop()
    return await loop_ev.run_in_executor(None, _sync_run)


# ---------------------------------------------------------------------------
# Route dependency helpers (injected from main app)
# ---------------------------------------------------------------------------

def _get_repo(settings: Settings = Depends(get_settings)) -> Repository:
    from kmbl_orchestrator.persistence.factory import get_repository
    return get_repository(settings)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/orchestrator/loops/start", response_model=LoopResponse)
def start_loop(
    body: StartLoopBody,
    repo: Repository = Depends(_get_repo),
) -> LoopResponse:
    """Start a new autonomous loop for an identity URL."""
    from kmbl_orchestrator.autonomous import start_autonomous_loop

    loop = start_autonomous_loop(
        repo,
        body.identity_url,
        max_iterations=body.max_iterations,
        auto_publish_threshold=body.auto_publish_threshold,
    )
    return LoopResponse(
        loop_id=str(loop.loop_id),
        identity_id=str(loop.identity_id),
        identity_url=loop.identity_url,
        status=loop.status,
        phase=loop.phase,
        iteration_count=loop.iteration_count,
        proposed_staging_id=str(loop.proposed_staging_id) if loop.proposed_staging_id else None,
    )


@router.get("/orchestrator/loops", response_model=list[LoopResponse])
def list_loops(
    repo: Repository = Depends(_get_repo),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
) -> list[LoopResponse]:
    """List autonomous loops."""
    loops = repo.list_autonomous_loops(status=status, limit=limit)
    return [
        LoopResponse(
            loop_id=str(loop.loop_id),
            identity_id=str(loop.identity_id),
            identity_url=loop.identity_url,
            status=loop.status,
            phase=loop.phase,
            iteration_count=loop.iteration_count,
            proposed_staging_id=str(loop.proposed_staging_id) if loop.proposed_staging_id else None,
        )
        for loop in loops
    ]


@router.get("/orchestrator/loops/{loop_id}")
def get_loop(
    loop_id: str,
    repo: Repository = Depends(_get_repo),
) -> dict[str, Any]:
    """Get details of an autonomous loop."""
    loop = repo.get_autonomous_loop(UUID(loop_id))
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")
    return {
        "loop_id": str(loop.loop_id),
        "identity_id": str(loop.identity_id),
        "identity_url": loop.identity_url,
        "status": loop.status,
        "phase": loop.phase,
        "iteration_count": loop.iteration_count,
        "max_iterations": loop.max_iterations,
        "current_thread_id": str(loop.current_thread_id) if loop.current_thread_id else None,
        "current_graph_run_id": str(loop.current_graph_run_id) if loop.current_graph_run_id else None,
        "last_staging_snapshot_id": str(loop.last_staging_snapshot_id) if loop.last_staging_snapshot_id else None,
        "last_evaluator_status": loop.last_evaluator_status,
        "last_evaluator_score": loop.last_evaluator_score,
        "last_alignment_score": loop.last_alignment_score,
        "exploration_directions": loop.exploration_directions,
        "completed_directions": loop.completed_directions,
        "auto_publish_threshold": loop.auto_publish_threshold,
        "proposed_staging_id": str(loop.proposed_staging_id) if loop.proposed_staging_id else None,
        "proposed_at": loop.proposed_at,
        "locked_at": loop.locked_at,
        "locked_by": loop.locked_by,
        "created_at": loop.created_at,
        "updated_at": loop.updated_at,
        "completed_at": loop.completed_at,
        "total_staging_count": loop.total_staging_count,
        "total_publication_count": loop.total_publication_count,
        "best_rating": loop.best_rating,
        "last_error": loop.last_error,
        "consecutive_graph_failures": loop.consecutive_graph_failures,
    }


@router.post("/orchestrator/cron/tick")
async def cron_tick(
    repo: Repository = Depends(_get_repo),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """
    Cron tick endpoint — called on a schedule (e.g. every minute).

    Acquires lock on the next pending loop and runs one tick.
    Returns immediately when no loops are pending or all are locked.
    """
    from kmbl_orchestrator.autonomous import tick_loop

    loop_record = repo.get_next_pending_loop()
    if loop_record is None:
        return {"status": "no_pending_loops", "action": None}

    worker_id = f"cron-{uuid4().hex[:8]}"
    acquired = repo.try_acquire_loop_lock(loop_record.loop_id, worker_id, lock_timeout_seconds=300)
    if not acquired:
        return {"status": "lock_contention", "loop_id": str(loop_record.loop_id), "action": None}

    try:
        async def _bridge(
            *,
            identity_url: str,
            identity_id: UUID,
            event_input: dict[str, Any],
            thread_id: UUID | None = None,
            retry_context: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return await run_graph_for_loop(
                repo=repo,
                settings=settings,
                identity_url=identity_url,
                identity_id=identity_id,
                event_input=event_input,
                thread_id=thread_id,
                retry_context=retry_context,
            )

        result = await tick_loop(repo, loop_record, run_graph_fn=_bridge)
        _log.info(
            "cron_tick_completed loop_id=%s identity_id=%s phase=%s action=%s error=%s",
            loop_record.loop_id,
            loop_record.identity_id,
            loop_record.phase,
            result.action,
            result.error,
        )
        return {"status": "tick_completed", **result.to_dict()}

    finally:
        repo.release_loop_lock(loop_record.loop_id)


@router.post("/orchestrator/loops/{loop_id}/pause")
def pause_loop(
    loop_id: str,
    repo: Repository = Depends(_get_repo),
) -> dict[str, str]:
    """Pause an autonomous loop."""
    loop = repo.get_autonomous_loop(UUID(loop_id))
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")
    if loop.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail=f"Cannot pause loop in status: {loop.status}")
    repo.update_loop_state(UUID(loop_id), status="paused")
    return {"status": "paused", "loop_id": loop_id}


@router.post("/orchestrator/loops/{loop_id}/resume")
def resume_loop(
    loop_id: str,
    repo: Repository = Depends(_get_repo),
) -> dict[str, str]:
    """Resume a paused autonomous loop."""
    loop = repo.get_autonomous_loop(UUID(loop_id))
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")
    if loop.status != "paused":
        raise HTTPException(status_code=400, detail=f"Cannot resume loop in status: {loop.status}")
    repo.update_loop_state(UUID(loop_id), status="running")
    return {"status": "running", "loop_id": loop_id}


@router.post("/orchestrator/loops/{loop_id}/interrupt")
def interrupt_loop(
    loop_id: str,
    body: InterruptBody,
    repo: Repository = Depends(_get_repo),
) -> dict[str, Any]:
    """Send an interrupt instruction to a running loop."""
    loop = repo.get_autonomous_loop(UUID(loop_id))
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")

    interrupt_direction = {
        "id": f"interrupt-{uuid4().hex[:8]}",
        "type": "user_interrupt",
        "message": body.message,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "priority": "high",
    }

    new_directions = (loop.exploration_directions or []) + [interrupt_direction]
    repo.update_loop_state(UUID(loop_id), exploration_directions=new_directions)

    return {
        "status": "interrupt_queued",
        "loop_id": loop_id,
        "interrupt_id": interrupt_direction["id"],
        "message": body.message,
    }
