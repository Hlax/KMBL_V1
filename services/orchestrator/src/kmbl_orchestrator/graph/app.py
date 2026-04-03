"""
LangGraph application — thread → context → checkpoint → planner → generator
→ evaluator → decision → (replan: planner | iterate: generator | staging | end).
"""

from __future__ import annotations

import logging
import time
from functools import partial
from typing import Any, Literal, cast
from datetime import datetime, timezone
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.contracts.normalized_errors import (
    error_kind_from_detail,
    staging_integrity_failure,
)
from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    CheckpointRecord,
    GraphRunRecord,
    ThreadRecord,
    is_valid_status_transition,
)
from kmbl_orchestrator.errors import (
    RoleInvocationFailed,
    RunInterrupted,
    StagingIntegrityFailed,
)
from kmbl_orchestrator.graph.helpers import (
    _apply_html_blocks_to_candidate as _apply_html_blocks_to_candidate_impl,
    _extract_html_file_map_from_working_staging,  # noqa: F401  re-export for tests
    _save_checkpoint_with_event,
    _uuid,
    compute_evaluator_decision,  # noqa: F401  re-export for tests
    maybe_suppress_duplicate_staging,  # noqa: F401  re-export for tests
    should_route_to_planner_on_iterate,  # noqa: F401  re-export for tests
)
from kmbl_orchestrator.graph.nodes import (
    context_hydrator as _context_hydrator,
    decision_router as _decision_router,
    evaluator_node as _evaluator_node,
    generator_node as _generator_node,
    planner_node as _planner_node,
    staging_node as _staging_node,
)
from kmbl_orchestrator.graph.state import GraphState
from kmbl_orchestrator.memory.ops import append_memory_event, record_run_outcome_memory
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker
from kmbl_orchestrator.runtime.interrupt_checks import raise_if_interrupt_requested
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event

_log = logging.getLogger(__name__)


class GraphContext:
    """Closure dependencies for graph nodes."""

    def __init__(
        self,
        repo: Repository,
        invoker: DefaultRoleInvoker,
        settings: Settings,
    ) -> None:
        self.repo = repo
        self.invoker = invoker
        self.settings = settings


def _apply_html_blocks_to_candidate(
    ctx_or_repo: "GraphContext | Repository",
    cand: "BuildCandidateRecord",
    tid: UUID,
) -> "BuildCandidateRecord":
    """Backward-compat wrapper: accepts GraphContext or bare Repository."""
    repo = ctx_or_repo.repo if isinstance(ctx_or_repo, GraphContext) else ctx_or_repo
    return _apply_html_blocks_to_candidate_impl(repo, cand, tid)


def build_graph_context(
    settings: Settings,
    repo: Repository,
    invoker: DefaultRoleInvoker | None = None,
) -> "GraphContext":
    """Public factory: create a ``GraphContext`` from settings and repo."""
    inv = invoker or DefaultRoleInvoker(settings=settings)
    return GraphContext(repo, inv, settings)


def get_compiled_graph(ctx: "GraphContext"):
    """Public factory: compile and return the LangGraph graph for a given context.

    The returned object supports both ``.invoke()`` (synchronous) and ``.ainvoke()``
    / ``.astream()`` (async) — use the appropriate form depending on your call site.
    """
    return build_compiled_graph(ctx)


def build_compiled_graph(ctx: GraphContext):
    def thread_resolver(state: GraphState) -> dict[str, Any]:
        tid = state.get("thread_id") or _uuid()
        gid = state.get("graph_run_id") or _uuid()
        return {"thread_id": tid, "graph_run_id": gid, "status": "running"}

    def checkpoint_pre(state: GraphState) -> dict[str, Any]:
        gid = UUID(state["graph_run_id"])
        tid = UUID(state["thread_id"])
        raise_if_interrupt_requested(ctx.repo, gid, tid)
        cp = CheckpointRecord(
            checkpoint_id=uuid4(),
            thread_id=UUID(state["thread_id"]),
            graph_run_id=gid,
            checkpoint_kind="pre_role",
            state_json={**dict(state), "_role_checkpoint_gate": "pre_graph"},
            context_compaction_json=None,
        )
        _save_checkpoint_with_event(ctx.repo, cp)
        return {}

    def route_after_decision(state: GraphState) -> str:
        d = state.get("decision")
        if d == "iterate":
            if should_route_to_planner_on_iterate(dict(state), ctx.settings):
                gid_raw = state.get("graph_run_id")
                tid_raw = state.get("thread_id")
                if gid_raw and tid_raw:
                    append_graph_run_event(
                        ctx.repo,
                        UUID(str(gid_raw)),
                        RunEventType.DECISION_ITERATE,
                        {
                            "next_node": "planner",
                            "retry_direction": state.get("retry_direction"),
                            "stagnation_count": (state.get("current_state") or {}).get(
                                "stagnation_count"
                            ),
                        },
                        thread_id=UUID(str(tid_raw)),
                    )
                return "planner"
            return "generator"
        if d == "stage":
            return "staging"
        return "end"

    graph = StateGraph(GraphState)
    graph.add_node("thread_resolver", thread_resolver)
    graph.add_node("context_hydrator", partial(_context_hydrator, ctx))
    graph.add_node("checkpoint_pre", checkpoint_pre)
    graph.add_node("planner", partial(_planner_node, ctx))
    graph.add_node("generator", partial(_generator_node, ctx))
    graph.add_node("evaluator", partial(_evaluator_node, ctx))
    graph.add_node("decision_router", partial(_decision_router, ctx))
    graph.add_node("staging", partial(_staging_node, ctx))

    graph.add_edge(START, "thread_resolver")
    graph.add_edge("thread_resolver", "context_hydrator")
    graph.add_edge("context_hydrator", "checkpoint_pre")
    graph.add_edge("checkpoint_pre", "planner")
    graph.add_edge("planner", "generator")
    graph.add_edge("generator", "evaluator")
    graph.add_edge("evaluator", "decision_router")
    graph.add_conditional_edges(
        "decision_router",
        route_after_decision,
        {
            "planner": "planner",
            "generator": "generator",
            "staging": "staging",
            "end": END,
        },
    )
    graph.add_edge("staging", END)
    return graph.compile()


def run_graph(
    *,
    repo: Repository,
    invoker: DefaultRoleInvoker | None = None,
    settings: Settings | None = None,
    initial: GraphState | None = None,
) -> GraphState:
    """
    Compile and invoke the LangGraph runtime (single-threaded).

    **Invariant:** the ``graph_run_id`` (and thread) must already exist in the
    repository. Call :func:`persist_graph_run_start` first. The public
    ``POST /orchestrator/runs/start`` handler persists first, then (asynchronously)
    invokes this — do not call ``run_graph`` with arbitrary IDs or you will hit
    FK errors / the guard below.

    Checkpoint ``state_json`` can grow; compaction/splitting is a later concern.
    """
    settings = settings or get_settings()
    invoker = invoker or DefaultRoleInvoker(settings=settings)
    ctx = GraphContext(repo, invoker, settings)
    app = build_compiled_graph(ctx)
    base: GraphState = {
        "iteration_index": 0,
        "max_iterations": settings.graph_max_iterations_default,
        "trigger_type": "prompt",
        "event_input": {},
    }
    if initial:
        base.update(initial)
    gid0 = base.get("graph_run_id")
    if gid0 and repo.get_graph_run(UUID(str(gid0))) is None:
        raise RuntimeError(
            "graph_run not found — call persist_graph_run_start() before run_graph() "
            "so thread and graph_run rows exist."
        )
    t_run = time.perf_counter()
    _log.info(
        "run_graph graph_run_id=%s stage=langgraph_invoke_start elapsed_ms=0.0",
        gid0,
    )
    # Acquire thread-level advisory lock to prevent interleaved writes
    _tid_raw = base.get("thread_id")
    _thread_lock_ctx = (
        repo.thread_lock(UUID(str(_tid_raw))) if _tid_raw else _noop_ctx()
    )
    with _thread_lock_ctx:
        return _run_graph_inner(repo, ctx, app, base, gid0, t_run)


def _noop_ctx():
    """Trivial context manager for the no-thread-id case."""
    from contextlib import nullcontext
    return nullcontext()


def _run_graph_inner(
    repo: Repository,
    ctx: GraphContext,
    app,
    base: dict[str, Any],
    gid0,
    t_run: float,
) -> GraphState:
    """Inner body of ``run_graph`` — runs inside the optional thread lock."""
    if gid0:
        gid_u = UUID(str(gid0))
        gr0 = repo.get_graph_run(gid_u)
        if gr0 is not None and gr0.status == "starting":
            repo.update_graph_run_status(
                gid_u, "running", None, clear_interrupt_requested=False
            )
        elif gr0 is not None and gr0.status not in ("running", "starting"):
            _log.error(
                "run_graph graph_run_id=%s invalid_status_for_invoke status=%s",
                gid0,
                gr0.status,
            )
            raise RuntimeError(
                f"graph_run {gid0} has status '{gr0.status}' — expected 'starting' or 'running'"
            )
    try:
        final = app.invoke(base)
    except RunInterrupted as e:
        ended = datetime.now(timezone.utc).isoformat()
        tid_u = e.thread_id
        append_graph_run_event(
            repo,
            e.graph_run_id,
            RunEventType.INTERRUPT_ACKNOWLEDGED,
            {},
            thread_id=tid_u,
        )
        append_graph_run_event(
            repo,
            e.graph_run_id,
            RunEventType.GRAPH_RUN_INTERRUPTED,
            {},
            thread_id=tid_u,
        )
        repo.update_graph_run_status(e.graph_run_id, "interrupted", ended)
        return {
            **base,
            "graph_run_id": str(e.graph_run_id),
            "thread_id": str(tid_u),
            "status": "interrupted",
        }
    except RoleInvocationFailed as e:
        if gid0:
            gid_u = UUID(str(gid0))
            tid_u = e.thread_id
            ek = error_kind_from_detail(e.detail) or "role_invocation"
            _save_checkpoint_with_event(
                ctx.repo,
                CheckpointRecord(
                    checkpoint_id=uuid4(),
                    thread_id=tid_u,
                    graph_run_id=gid_u,
                    checkpoint_kind="interrupt",
                    state_json={
                        "orchestrator_error": {
                            "error_kind": ek,
                            "error_message": str(
                                e.detail.get("message", "role invocation failed")
                            ),
                            "failure": e.detail,
                            "failure_phase": e.phase,
                        }
                    },
                    context_compaction_json=None,
                ),
            )
            append_graph_run_event(
                repo,
                gid_u,
                RunEventType.GRAPH_RUN_FAILED,
                {"phase": e.phase, "error_kind": ek},
            )
            repo.update_graph_run_status(
                gid_u,
                "failed",
                datetime.now(timezone.utc).isoformat(),
            )
        raise
    except StagingIntegrityFailed as e:
        if gid0:
            gid_u = UUID(str(gid0))
            tid_u = e.thread_id
            failure = staging_integrity_failure(
                reason=e.reason,
                message=e.message,
                details=e.detail if e.detail else None,
            )
            _save_checkpoint_with_event(
                ctx.repo,
                CheckpointRecord(
                    checkpoint_id=uuid4(),
                    thread_id=tid_u,
                    graph_run_id=gid_u,
                    checkpoint_kind="interrupt",
                    state_json={
                        "orchestrator_error": {
                            "error_kind": "staging_integrity",
                            "error_message": e.message,
                            "failure": failure,
                            "staging_reason": e.reason,
                        }
                    },
                    context_compaction_json=None,
                ),
            )
            append_graph_run_event(
                repo,
                gid_u,
                RunEventType.GRAPH_RUN_FAILED,
                {
                    "error_kind": "staging_integrity",
                    "staging_reason": e.reason,
                },
            )
            repo.update_graph_run_status(
                gid_u,
                "failed",
                datetime.now(timezone.utc).isoformat(),
            )
        raise
    except Exception as e:
        if gid0:
            gid_u = UUID(str(gid0))
            tid_s = base.get("thread_id")
            error_info: dict[str, Any] = {
                "error_kind": "graph_error",
                "error_type": type(e).__name__,
                "error_message": str(e)[:500],
            }
            if tid_s:
                tid_u = UUID(str(tid_s))
                _save_checkpoint_with_event(
                    ctx.repo,
                    CheckpointRecord(
                        checkpoint_id=uuid4(),
                        thread_id=tid_u,
                        graph_run_id=gid_u,
                        checkpoint_kind="interrupt",
                        state_json={"orchestrator_error": error_info},
                        context_compaction_json=None,
                    ),
                )
                append_graph_run_event(
                    repo,
                    gid_u,
                    RunEventType.GRAPH_RUN_FAILED,
                    error_info,
                )
            repo.update_graph_run_status(
                gid_u,
                "failed",
                datetime.now(timezone.utc).isoformat(),
            )
        raise

    # --- Post-invoke success path (wrapped for resilience) ---
    assert isinstance(final, dict)
    gid = final.get("graph_run_id")
    if gid:
        tid_s = final.get("thread_id")
        gid_u = UUID(gid)
        tid_u = UUID(tid_s) if tid_s else None
        try:
            with repo.transaction():
                if tid_s:
                    post = CheckpointRecord(
                        checkpoint_id=uuid4(),
                        thread_id=UUID(tid_s),
                        graph_run_id=gid_u,
                        checkpoint_kind="post_role",
                        state_json=dict(final),
                        context_compaction_json=None,
                    )
                    _save_checkpoint_with_event(ctx.repo, post)
                    repo.update_thread_current_checkpoint(UUID(tid_s), post.checkpoint_id)
                ended = datetime.now(timezone.utc).isoformat()
                # Validate status transition before applying
                current_run = repo.get_graph_run(gid_u)
                if current_run and not is_valid_status_transition(current_run.status, "completed"):
                    _log.warning(
                        "run_graph graph_run_id=%s invalid_transition current=%s target=completed",
                        gid, current_run.status,
                    )
                repo.update_graph_run_status(gid_u, "completed", ended)
                repo.attach_run_snapshot(gid_u, dict(final))
                append_graph_run_event(
                    repo,
                    gid_u,
                    RunEventType.GRAPH_RUN_COMPLETED,
                    {
                        "decision": final.get("decision"),
                        "iteration_index": final.get("iteration_index"),
                        "staging_snapshot_id": final.get("staging_snapshot_id"),
                        "last_alignment_score": final.get("last_alignment_score"),
                    },
                    thread_id=tid_u,
                )
                wt = record_run_outcome_memory(
                    repo,
                    graph_run_id=gid_u,
                    settings=ctx.settings,
                    final_state=dict(final),
                )
                if wt is not None:
                    append_memory_event(
                        repo,
                        graph_run_id=gid_u,
                        thread_id=tid_u,
                        kind="updated",
                        payload={
                            "memory_keys_written": wt.memory_keys_written,
                            "categories": wt.categories,
                            "phase": "run_outcome",
                        },
                    )
        except Exception as post_exc:
            _log.exception(
                "run_graph post-invoke persistence failed graph_run_id=%s exc=%s",
                gid,
                type(post_exc).__name__,
            )
            append_graph_run_event(
                repo,
                gid_u,
                RunEventType.POST_INVOKE_FAILURE,
                {
                    "error_type": type(post_exc).__name__,
                    "error_message": str(post_exc)[:500],
                    "phase": "post_invoke_persistence",
                },
                thread_id=tid_u,
            )
            try:
                repo.update_graph_run_status(
                    gid_u,
                    "failed",
                    datetime.now(timezone.utc).isoformat(),
                )
            except Exception:
                _log.exception(
                    "run_graph failed to mark run as failed graph_run_id=%s", gid
                )
            raise
    _log.info(
        "run_graph graph_run_id=%s stage=response_returning elapsed_ms=%.1f",
        final.get("graph_run_id", gid0),
        (time.perf_counter() - t_run) * 1000,
    )
    return final  # type: ignore[return-value]


def persist_graph_run_start(
    repo: Repository,
    *,
    thread_id: str | None,
    graph_run_id: str | None,
    identity_id: str | None,
    trigger_type: str,
    event_input: dict[str, Any],
) -> tuple[str, str]:
    """Ensure thread + graph_run rows exist; return (thread_id, graph_run_id)."""
    t0 = time.perf_counter()
    tid = thread_id or _uuid()
    gid = graph_run_id or _uuid()
    tid_u = UUID(tid)
    repo.ensure_thread(
        ThreadRecord(
            thread_id=tid_u,
            identity_id=UUID(identity_id) if identity_id else None,
            thread_kind="build",
            status="active",
        )
    )
    _log.info(
        "persist_graph_run_start graph_run_id=%s thread_id=%s stage=thread_resolved elapsed_ms=%.1f",
        gid,
        tid,
        (time.perf_counter() - t0) * 1000,
    )
    gr = GraphRunRecord(
        graph_run_id=UUID(gid),
        thread_id=tid_u,
        identity_id=UUID(identity_id) if identity_id else None,
        trigger_type=cast(
            Literal[
                "prompt",
                "resume",
                "schedule",
                "system",
                "autonomous_loop",
            ],
            trigger_type,
        ),
        status="starting",
    )
    repo.save_graph_run(gr)
    append_graph_run_event(repo, UUID(gid), RunEventType.GRAPH_RUN_STARTED, {}, thread_id=tid_u)
    _log.info(
        "persist_graph_run_start graph_run_id=%s thread_id=%s stage=graph_run_persisted elapsed_ms=%.1f",
        gid,
        tid,
        (time.perf_counter() - t0) * 1000,
    )
    _ = event_input
    return tid, gid
