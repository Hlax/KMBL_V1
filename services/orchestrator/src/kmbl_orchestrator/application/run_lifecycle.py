"""Background graph execution and start-run event_input resolution."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.domain import CheckpointRecord
from kmbl_orchestrator.errors import RoleInvocationFailed, StagingIntegrityFailed
from kmbl_orchestrator.graph.app import run_graph
from kmbl_orchestrator.persistence.factory import get_repository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker
from kmbl_orchestrator.runtime.smoke_planner import run_smoke_planner_only
from kmbl_orchestrator.application.start_event_input_resolution import resolve_start_event_input

_log = logging.getLogger(__name__)


def run_graph_background(
    *,
    thread_id: str,
    graph_run_id: str,
    identity_id: str | None,
    trigger_type: str,
    event_input: dict[str, Any],
    max_iterations: int | None = None,
) -> None:
    """Run LangGraph after HTTP returns; same-process thread pool (local dev)."""
    settings = get_settings()
    repo = get_repository(settings)
    invoker = DefaultRoleInvoker(settings=settings)
    gid_u = UUID(graph_run_id)
    tid_u = UUID(thread_id)
    t_bg = time.perf_counter()
    _log.info(
        "run_start_background graph_run_id=%s stage=background_graph_enter elapsed_ms=0.0",
        graph_run_id,
    )
    if settings.orchestrator_smoke_planner_only:
        _log.warning(
            "run_start_background graph_run_id=%s mode=ORCHESTRATOR_SMOKE_PLANNER_ONLY (single planner HTTP only)",
            graph_run_id,
        )
        try:
            run_smoke_planner_only(
                repo=repo,
                invoker=invoker,
                settings=settings,
                thread_id=thread_id,
                graph_run_id=graph_run_id,
                event_input=event_input,
            )
        except Exception:
            _log.exception(
                "smoke_planner_only failed graph_run_id=%s",
                graph_run_id,
            )
            try:
                repo.update_graph_run_status(
                    gid_u,
                    "failed",
                    datetime.now(timezone.utc).isoformat(),
                )
            except Exception:
                _log.exception(
                    "Could not mark graph_run failed after smoke error (graph_run_id=%s)",
                    graph_run_id,
                )
        else:
            _log.info(
                "run_start_background graph_run_id=%s stage=background_graph_exit_ok elapsed_ms=%.1f",
                graph_run_id,
                (time.perf_counter() - t_bg) * 1000,
            )
        return
    try:
        mi = max_iterations if max_iterations is not None else settings.graph_max_iterations_default
        final = run_graph(
            repo=repo,
            invoker=invoker,
            settings=settings,
            initial={
                "thread_id": thread_id,
                "graph_run_id": graph_run_id,
                "identity_id": identity_id,
                "trigger_type": trigger_type,
                "event_input": event_input,
                "max_iterations": mi,
            },
        )
    except RoleInvocationFailed as e:
        _log.exception(
            "Background graph run RoleInvocationFailed stage=%s graph_run_id=%s",
            e.phase,
            graph_run_id,
        )
    except StagingIntegrityFailed as e:
        _log.exception(
            "Background graph run StagingIntegrityFailed stage=staging_reason=%s graph_run_id=%s",
            e.reason,
            graph_run_id,
        )
    except Exception as e:
        _log.exception(
            "Background graph run failed stage=unhandled graph_run_id=%s exc=%s",
            graph_run_id,
            type(e).__name__,
        )
        try:
            repo.update_graph_run_status(
                gid_u,
                "failed",
                datetime.now(timezone.utc).isoformat(),
            )
            repo.save_checkpoint(
                CheckpointRecord(
                    checkpoint_id=uuid4(),
                    thread_id=tid_u,
                    graph_run_id=gid_u,
                    checkpoint_kind="interrupt",
                    state_json={
                        "orchestrator_error": {
                            "error_kind": "graph_error",
                            "error_message": f"{type(e).__name__}: {e}",
                        }
                    },
                    context_compaction_json=None,
                )
            )
        except Exception:
            _log.exception(
                "Could not persist failed status / interrupt checkpoint (graph_run_id=%s)",
                graph_run_id,
            )
    else:
        _log.info(
            "run_start_background graph_run_id=%s stage=background_graph_exit_ok elapsed_ms=%.1f",
            graph_run_id,
            (time.perf_counter() - t_bg) * 1000,
        )
        # Same crawl closure as autonomous loop tick: advance frontier + optional Playwright
        # so Autonomous page ``POST /runs/start`` loops see durable crawl progress.
        if identity_id and isinstance(final, dict):
            try:
                from kmbl_orchestrator.autonomous.loop_service import (
                    advance_crawl_frontier_after_graph,
                )

                advance_crawl_frontier_after_graph(
                    repo,
                    dict(final),
                    identity_id=UUID(identity_id),
                    thread_id=tid_u,
                    context_label=f"runs_start/{graph_run_id}",
                )
            except Exception as exc:
                _log.warning(
                    "crawl frontier advance after runs/start failed graph_run_id=%s: %s",
                    graph_run_id,
                    str(exc)[:200],
                )
