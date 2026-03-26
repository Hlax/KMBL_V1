"""
LangGraph application — minimal v1: thread → context → checkpoint → planner → generator
→ evaluator → decision → (iterate | staging | end).

TODO: interrupt_node, publication_node, richer context compaction (docs/08 §8).
"""

from __future__ import annotations

from typing import Any, Literal, cast
from datetime import datetime, timezone
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.domain import CheckpointRecord, GraphRunRecord
from kmbl_orchestrator.errors import RoleInvocationFailed
from kmbl_orchestrator.graph.state import GraphState
from kmbl_orchestrator.normalize import (
    normalize_evaluator_output,
    normalize_generator_output,
    normalize_planner_output,
)
from kmbl_orchestrator.domain import ThreadRecord
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker


def _uuid() -> str:
    return str(uuid4())


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


def build_compiled_graph(ctx: GraphContext):
    def thread_resolver(state: GraphState) -> dict[str, Any]:
        tid = state.get("thread_id") or _uuid()
        gid = state.get("graph_run_id") or _uuid()
        return {"thread_id": tid, "graph_run_id": gid, "status": "running"}

    def context_hydrator(state: GraphState) -> dict[str, Any]:
        # TODO: load identity_profile + identity_memory from Supabase (docs/07, docs/08 §3.3).
        return {
            "identity_context": state.get("identity_context") or {},
            "memory_context": state.get("memory_context") or {},
            "current_state": state.get("current_state") or {},
            "compacted_context": state.get("compacted_context") or {},
        }

    def checkpoint_pre(state: GraphState) -> dict[str, Any]:
        cp = CheckpointRecord(
            checkpoint_id=uuid4(),
            thread_id=UUID(state["thread_id"]),
            graph_run_id=UUID(state["graph_run_id"]),
            checkpoint_kind="pre_role",
            state_json=dict(state),
            context_compaction_json=None,
        )
        ctx.repo.save_checkpoint(cp)
        return {}

    def planner_node(state: GraphState) -> dict[str, Any]:
        gid = UUID(state["graph_run_id"])
        tid = UUID(state["thread_id"])
        payload = {
            "thread_id": state["thread_id"],
            "identity_context": state.get("identity_context") or {},
            "memory_context": state.get("memory_context") or {},
            "event_input": state.get("event_input") or {},
            "current_state_summary": state.get("current_state") or {},
        }
        inv, raw = ctx.invoker.invoke(
            graph_run_id=gid,
            thread_id=tid,
            role_type="planner",
            provider_config_key=ctx.settings.kiloclaw_planner_config_key,
            input_payload=payload,
            iteration_index=state.get("iteration_index", 0),
        )
        ctx.repo.save_role_invocation(inv)
        if inv.status == "failed":
            raise RoleInvocationFailed(
                phase="planner",
                graph_run_id=gid,
                thread_id=tid,
                detail=raw,
            )
        spec = normalize_planner_output(
            raw,
            thread_id=tid,
            graph_run_id=gid,
            planner_invocation_id=inv.role_invocation_id,
        )
        spec = spec.model_copy(update={"raw_payload_json": raw})
        ctx.repo.save_build_spec(spec)
        return {
            "build_spec": raw.get("build_spec"),
            "build_spec_id": str(spec.build_spec_id),
        }

    def generator_node(state: GraphState) -> dict[str, Any]:
        gid = UUID(state["graph_run_id"])
        tid = UUID(state["thread_id"])
        bsid = state.get("build_spec_id")
        if not bsid:
            raise RuntimeError("build_spec_id required before generator")
        iteration = int(state.get("iteration_index", 0))
        feedback: Any = None
        if iteration > 0:
            feedback = state.get("evaluation_report")
        payload = {
            "thread_id": state["thread_id"],
            "build_spec": state.get("build_spec") or {},
            "current_working_state": state.get("current_state") or {},
            "iteration_feedback": feedback,
        }
        inv, raw = ctx.invoker.invoke(
            graph_run_id=gid,
            thread_id=tid,
            role_type="generator",
            provider_config_key=ctx.settings.kiloclaw_generator_config_key,
            input_payload=payload,
            iteration_index=iteration,
        )
        ctx.repo.save_role_invocation(inv)
        if inv.status == "failed":
            raise RoleInvocationFailed(
                phase="generator",
                graph_run_id=gid,
                thread_id=tid,
                detail=raw,
            )
        cand = normalize_generator_output(
            raw,
            thread_id=tid,
            graph_run_id=gid,
            generator_invocation_id=inv.role_invocation_id,
            build_spec_id=UUID(bsid),
        )
        cand = cand.model_copy(update={"raw_payload_json": raw})
        ctx.repo.save_build_candidate(cand)
        return {
            "build_candidate": {
                "proposed_changes": raw.get("proposed_changes"),
                "artifact_outputs": raw.get("artifact_outputs"),
                "updated_state": raw.get("updated_state"),
                "sandbox_ref": raw.get("sandbox_ref"),
                "preview_url": raw.get("preview_url"),
            },
            "build_candidate_id": str(cand.build_candidate_id),
            "current_state": raw.get("updated_state") or state.get("current_state") or {},
        }

    def evaluator_node(state: GraphState) -> dict[str, Any]:
        gid = UUID(state["graph_run_id"])
        tid = UUID(state["thread_id"])
        bcid = state.get("build_candidate_id")
        bsid = state.get("build_spec_id")
        if not bcid or not bsid:
            raise RuntimeError("build_candidate_id and build_spec_id required before evaluator")
        spec = ctx.repo.get_build_spec(UUID(bsid))
        success = spec.success_criteria_json if spec else []
        targets = spec.evaluation_targets_json if spec else []
        payload = {
            "thread_id": state["thread_id"],
            "build_candidate": state.get("build_candidate") or {},
            "success_criteria": success,
            "evaluation_targets": targets,
            "iteration_hint": state.get("iteration_index", 0),
        }
        inv, raw = ctx.invoker.invoke(
            graph_run_id=gid,
            thread_id=tid,
            role_type="evaluator",
            provider_config_key=ctx.settings.kiloclaw_evaluator_config_key,
            input_payload=payload,
            iteration_index=int(state.get("iteration_index", 0)),
        )
        ctx.repo.save_role_invocation(inv)
        if inv.status == "failed":
            raise RoleInvocationFailed(
                phase="evaluator",
                graph_run_id=gid,
                thread_id=tid,
                detail=raw,
            )
        report = normalize_evaluator_output(
            raw,
            thread_id=tid,
            graph_run_id=gid,
            evaluator_invocation_id=inv.role_invocation_id,
            build_candidate_id=UUID(bcid),
        )
        report = report.model_copy(update={"raw_payload_json": raw})
        ctx.repo.save_evaluation_report(report)
        return {
            "evaluation_report": {
                "status": raw.get("status"),
                "summary": raw.get("summary"),
                "issues": raw.get("issues"),
                "metrics": raw.get("metrics"),
                "artifacts": raw.get("artifacts"),
            },
            "evaluation_report_id": str(report.evaluation_report_id),
        }

    def decision_router(state: GraphState) -> dict[str, Any]:
        ev = state.get("evaluation_report") or {}
        status = ev.get("status", "fail")
        iteration = int(state.get("iteration_index", 0))
        max_iter = int(state.get("max_iterations", 3))

        decision: Literal["stage", "iterate", "interrupt"]
        interrupt_reason: str | None = None
        if status == "pass":
            decision = "stage"
        elif status == "blocked":
            decision = "interrupt"
            interrupt_reason = "evaluator_blocked"
        elif status in ("fail", "partial"):
            if iteration < max_iter:
                decision = "iterate"
            else:
                decision = "interrupt"
                interrupt_reason = "max_iterations"
        else:
            decision = "interrupt"
            interrupt_reason = "unknown_eval_status"

        out: dict[str, Any] = {"decision": decision}
        if decision == "iterate":
            out["iteration_index"] = iteration + 1
        if interrupt_reason:
            out["interrupt_reason"] = interrupt_reason
        return out

    def staging_node(state: GraphState) -> dict[str, Any]:
        # TODO: persist staging_snapshot table (docs/07 §1.11).
        ssid = _uuid()
        return {"staging_snapshot_id": ssid, "status": "completed"}

    def route_after_decision(state: GraphState) -> str:
        d = state.get("decision")
        if d == "iterate":
            return "generator"
        if d == "stage":
            return "staging"
        return "end"

    graph = StateGraph(GraphState)
    graph.add_node("thread_resolver", thread_resolver)
    graph.add_node("context_hydrator", context_hydrator)
    graph.add_node("checkpoint_pre", checkpoint_pre)
    graph.add_node("planner", planner_node)
    graph.add_node("generator", generator_node)
    graph.add_node("evaluator", evaluator_node)
    graph.add_node("decision_router", decision_router)
    graph.add_node("staging", staging_node)

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
    ``POST /orchestrator/runs/start`` handler does this in order — do not call
    ``run_graph`` with arbitrary IDs or you will hit FK errors / the guard below.

    Checkpoint ``state_json`` can grow; compaction/splitting is a later concern.
    """
    settings = settings or get_settings()
    invoker = invoker or DefaultRoleInvoker(settings=settings)
    ctx = GraphContext(repo, invoker, settings)
    app = build_compiled_graph(ctx)
    base: GraphState = {
        "iteration_index": 0,
        "max_iterations": 3,
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
    try:
        final = app.invoke(base)
    except RoleInvocationFailed:
        if gid0:
            repo.update_graph_run_status(
                UUID(str(gid0)),
                "failed",
                datetime.now(timezone.utc).isoformat(),
            )
        raise
    assert isinstance(final, dict)
    gid = final.get("graph_run_id")
    if gid:
        tid_s = final.get("thread_id")
        if tid_s:
            post = CheckpointRecord(
                checkpoint_id=uuid4(),
                thread_id=UUID(tid_s),
                graph_run_id=UUID(gid),
                checkpoint_kind="post_role",
                state_json=dict(final),
                context_compaction_json=None,
            )
            repo.save_checkpoint(post)
            repo.update_thread_current_checkpoint(UUID(tid_s), post.checkpoint_id)
        ended = datetime.now(timezone.utc).isoformat()
        repo.update_graph_run_status(UUID(gid), "completed", ended)
        repo.attach_run_snapshot(UUID(gid), dict(final))
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
    gr = GraphRunRecord(
        graph_run_id=UUID(gid),
        thread_id=tid_u,
        trigger_type=cast(
            Literal["prompt", "resume", "schedule", "system"], trigger_type
        ),
        status="running",
    )
    repo.save_graph_run(gr)
    _ = event_input
    return tid, gid
