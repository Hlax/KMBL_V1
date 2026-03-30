"""
LangGraph application — minimal v1: thread → context → checkpoint → planner → generator
→ evaluator → decision → (iterate | staging | end).

TODO: interrupt_node, publication_node, richer context compaction (docs/08 §8).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal, cast
from datetime import datetime, timezone
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.contracts.normalized_errors import (
    contract_validation_failure,
    error_kind_from_detail,
    staging_integrity_failure,
)
from kmbl_orchestrator.contracts.persistence_validate import (
    validate_role_output_for_persistence,
)
from kmbl_orchestrator.contracts.planner_normalize import (
    normalize_build_spec_for_persistence,
)
from kmbl_orchestrator.domain import CheckpointRecord, GraphRunRecord, StagingSnapshotRecord
from kmbl_orchestrator.errors import RoleInvocationFailed, StagingIntegrityFailed
from kmbl_orchestrator.graph.state import GraphState
from kmbl_orchestrator.identity.hydrate import build_planner_identity_context
from kmbl_orchestrator.normalize import (
    normalize_evaluator_output,
    normalize_generator_output,
    normalize_planner_output,
)
from kmbl_orchestrator.normalize.gallery_strip_harness import (
    merge_gallery_strip_harness_checks,
)
from kmbl_orchestrator.domain import ThreadRecord
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.staging.build_snapshot import build_staging_snapshot_payload
from kmbl_orchestrator.staging.integrity import (
    validate_generator_output_for_candidate,
    validate_preview_integrity,
)
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker
from kmbl_orchestrator.runtime.kilo_model_routing import (
    ImageRouteBudgetExceededError,
    ImageRouteConfigurationError,
    select_generator_provider_config,
)
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event

_log = logging.getLogger(__name__)


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


def _save_checkpoint_with_event(
    ctx: GraphContext,
    record: CheckpointRecord,
) -> None:
    ctx.repo.save_checkpoint(record)
    append_graph_run_event(
        ctx.repo,
        record.graph_run_id,
        RunEventType.CHECKPOINT_WRITTEN,
        {
            "checkpoint_kind": record.checkpoint_kind,
            "checkpoint_id": str(record.checkpoint_id),
        },
    )


def _persist_invocation_failure(
    *,
    inv: Any,
    raw_detail: dict[str, Any],
    phase: Literal["planner", "generator", "evaluator"],
    graph_run_id: UUID,
    thread_id: UUID,
    repo: Repository,
) -> None:
    ended = datetime.now(timezone.utc).isoformat()
    failed = inv.model_copy(
        update={
            "output_payload_json": raw_detail,
            "status": "failed",
            "ended_at": ended,
        }
    )
    repo.save_role_invocation(failed)
    raise RoleInvocationFailed(
        phase=phase,
        graph_run_id=graph_run_id,
        thread_id=thread_id,
        detail=raw_detail,
    )


def build_compiled_graph(ctx: GraphContext):
    def thread_resolver(state: GraphState) -> dict[str, Any]:
        tid = state.get("thread_id") or _uuid()
        gid = state.get("graph_run_id") or _uuid()
        return {"thread_id": tid, "graph_run_id": gid, "status": "running"}

    def context_hydrator(state: GraphState) -> dict[str, Any]:
        iid_raw = state.get("identity_id")
        if iid_raw:
            try:
                ic = build_planner_identity_context(ctx.repo, UUID(str(iid_raw)))
            except ValueError:
                ic = {}
        else:
            ic = state.get("identity_context") or {}
        return {
            "identity_context": ic,
            "memory_context": state.get("memory_context") or {},
            "current_state": state.get("current_state") or {},
            "compacted_context": state.get("compacted_context") or {},
        }

    def checkpoint_pre(state: GraphState) -> dict[str, Any]:
        gid = UUID(state["graph_run_id"])
        cp = CheckpointRecord(
            checkpoint_id=uuid4(),
            thread_id=UUID(state["thread_id"]),
            graph_run_id=gid,
            checkpoint_kind="pre_role",
            state_json={**dict(state), "_role_checkpoint_gate": "pre_graph"},
            context_compaction_json=None,
        )
        _save_checkpoint_with_event(ctx, cp)
        return {}

    def planner_node(state: GraphState) -> dict[str, Any]:
        gid = UUID(state["graph_run_id"])
        tid = UUID(state["thread_id"])
        cp0 = CheckpointRecord(
            checkpoint_id=uuid4(),
            thread_id=tid,
            graph_run_id=gid,
            checkpoint_kind="pre_role",
            state_json={**dict(state), "_role_checkpoint_gate": "pre_planner"},
            context_compaction_json=None,
        )
        _save_checkpoint_with_event(ctx, cp0)
        append_graph_run_event(ctx.repo, gid, RunEventType.PLANNER_INVOCATION_STARTED, {})
        _log.info(
            "graph_run graph_run_id=%s stage=planner_invocation_start elapsed_ms=0.0",
            gid,
        )

        payload = {
            "thread_id": state["thread_id"],
            "identity_context": state.get("identity_context") or {},
            "memory_context": state.get("memory_context") or {},
            "event_input": state.get("event_input") or {},
            "current_state_summary": state.get("current_state") or {},
        }
        t_pl = time.perf_counter()
        inv, raw = ctx.invoker.invoke(
            graph_run_id=gid,
            thread_id=tid,
            role_type="planner",
            provider_config_key=ctx.settings.kiloclaw_planner_config_key,
            input_payload=payload,
            iteration_index=state.get("iteration_index", 0),
        )
        _log.info(
            "graph_run graph_run_id=%s stage=planner_invocation_finished elapsed_ms=%.1f",
            gid,
            (time.perf_counter() - t_pl) * 1000,
        )
        if inv.status == "failed":
            ctx.repo.save_role_invocation(inv)
            raise RoleInvocationFailed(
                phase="planner",
                graph_run_id=gid,
                thread_id=tid,
                detail=raw,
            )
        if not isinstance(raw.get("build_spec"), dict):
            raw["build_spec"] = {}
        norm_bs, normalized_fields = normalize_build_spec_for_persistence(raw["build_spec"])
        raw["build_spec"] = norm_bs
        if normalized_fields:
            md = raw.setdefault("_kmbl_planner_metadata", {})
            md["normalized_missing_fields"] = normalized_fields
        try:
            validate_role_output_for_persistence("planner", raw)
        except (ValidationError, ValueError) as e:
            pe = e.errors() if isinstance(e, ValidationError) else None
            msg = (
                "Persist-time validation failed"
                if isinstance(e, ValidationError)
                else str(e)
            )
            detail = contract_validation_failure(
                phase="planner",
                message=msg,
                pydantic_errors=pe,
            )
            _persist_invocation_failure(
                inv=inv,
                raw_detail=detail,
                phase="planner",
                graph_run_id=gid,
                thread_id=tid,
                repo=ctx.repo,
            )

        ctx.repo.save_role_invocation(inv)
        spec = normalize_planner_output(
            raw,
            thread_id=tid,
            graph_run_id=gid,
            planner_invocation_id=inv.role_invocation_id,
        )
        spec = spec.model_copy(update={"raw_payload_json": raw})
        ctx.repo.save_build_spec(spec)
        step_state = {
            **dict(state),
            "build_spec": raw.get("build_spec"),
            "build_spec_id": str(spec.build_spec_id),
        }
        _save_checkpoint_with_event(
            ctx,
            CheckpointRecord(
                checkpoint_id=uuid4(),
                thread_id=tid,
                graph_run_id=gid,
                checkpoint_kind="post_step",
                state_json=step_state,
                context_compaction_json=None,
            ),
        )
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.PLANNER_INVOCATION_COMPLETED,
            {"build_spec_id": str(spec.build_spec_id)},
        )
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
        cp0 = CheckpointRecord(
            checkpoint_id=uuid4(),
            thread_id=tid,
            graph_run_id=gid,
            checkpoint_kind="pre_role",
            state_json={**dict(state), "_role_checkpoint_gate": "pre_generator"},
            context_compaction_json=None,
        )
        _save_checkpoint_with_event(ctx, cp0)
        append_graph_run_event(ctx.repo, gid, RunEventType.GENERATOR_INVOCATION_STARTED, {})
        _log.info(
            "graph_run graph_run_id=%s stage=generator_invocation_start elapsed_ms=0.0",
            gid,
        )

        iteration = int(state.get("iteration_index", 0))
        feedback: Any = None
        if iteration > 0:
            feedback = state.get("evaluation_report")
        payload = {
            "thread_id": state["thread_id"],
            "build_spec": state.get("build_spec") or {},
            "current_working_state": state.get("current_state") or {},
            "iteration_feedback": feedback,
            "event_input": state.get("event_input") or {},
        }
        try:
            gen_key, routing_meta = select_generator_provider_config(
                ctx.settings,
                build_spec=state.get("build_spec") or {},
                event_input=state.get("event_input") or {},
                generator_payload=payload,
            )
        except (ImageRouteConfigurationError, ImageRouteBudgetExceededError) as e:
            detail = contract_validation_failure(
                phase="generator",
                message=str(e),
                pydantic_errors=None,
            )
            raise RoleInvocationFailed(
                phase="generator",
                graph_run_id=gid,
                thread_id=tid,
                detail=detail,
            ) from e
        t_gen = time.perf_counter()
        inv, raw = ctx.invoker.invoke(
            graph_run_id=gid,
            thread_id=tid,
            role_type="generator",
            provider_config_key=gen_key,
            input_payload=payload,
            iteration_index=iteration,
            routing_metadata=routing_meta,
        )
        _log.info(
            "graph_run graph_run_id=%s stage=generator_invocation_finished elapsed_ms=%.1f",
            gid,
            (time.perf_counter() - t_gen) * 1000,
        )
        if inv.status == "failed":
            ctx.repo.save_role_invocation(inv)
            raise RoleInvocationFailed(
                phase="generator",
                graph_run_id=gid,
                thread_id=tid,
                detail=raw,
            )
        try:
            validate_generator_output_for_candidate(raw)
        except ValueError as e:
            detail = contract_validation_failure(
                phase="generator",
                message=str(e),
                pydantic_errors=None,
            )
            _persist_invocation_failure(
                inv=inv,
                raw_detail=detail,
                phase="generator",
                graph_run_id=gid,
                thread_id=tid,
                repo=ctx.repo,
            )
        try:
            validate_role_output_for_persistence("generator", raw)
        except (ValidationError, ValueError) as e:
            pe = e.errors() if isinstance(e, ValidationError) else None
            msg = (
                "Persist-time validation failed"
                if isinstance(e, ValidationError)
                else str(e)
            )
            detail = contract_validation_failure(
                phase="generator",
                message=msg,
                pydantic_errors=pe,
            )
            _persist_invocation_failure(
                inv=inv,
                raw_detail=detail,
                phase="generator",
                graph_run_id=gid,
                thread_id=tid,
                repo=ctx.repo,
            )

        ctx.repo.save_role_invocation(inv)
        cand = normalize_generator_output(
            raw,
            thread_id=tid,
            graph_run_id=gid,
            generator_invocation_id=inv.role_invocation_id,
            build_spec_id=UUID(bsid),
        )
        cand = cand.model_copy(update={"raw_payload_json": raw})
        ctx.repo.save_build_candidate(cand)
        step_state = {
            **dict(state),
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
        _save_checkpoint_with_event(
            ctx,
            CheckpointRecord(
                checkpoint_id=uuid4(),
                thread_id=tid,
                graph_run_id=gid,
                checkpoint_kind="post_step",
                state_json=step_state,
                context_compaction_json=None,
            ),
        )
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.GENERATOR_INVOCATION_COMPLETED,
            {"build_candidate_id": str(cand.build_candidate_id)},
        )
        return {
            "build_candidate": step_state["build_candidate"],
            "build_candidate_id": str(cand.build_candidate_id),
            "current_state": step_state["current_state"],
        }

    def evaluator_node(state: GraphState) -> dict[str, Any]:
        gid = UUID(state["graph_run_id"])
        tid = UUID(state["thread_id"])
        bcid = state.get("build_candidate_id")
        bsid = state.get("build_spec_id")
        if not bcid or not bsid:
            raise RuntimeError("build_candidate_id and build_spec_id required before evaluator")
        cp0 = CheckpointRecord(
            checkpoint_id=uuid4(),
            thread_id=tid,
            graph_run_id=gid,
            checkpoint_kind="pre_role",
            state_json={**dict(state), "_role_checkpoint_gate": "pre_evaluator"},
            context_compaction_json=None,
        )
        _save_checkpoint_with_event(ctx, cp0)
        append_graph_run_event(ctx.repo, gid, RunEventType.EVALUATOR_INVOCATION_STARTED, {})
        _log.info(
            "graph_run graph_run_id=%s stage=evaluator_invocation_start elapsed_ms=0.0",
            gid,
        )

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
        t_ev = time.perf_counter()
        inv, raw = ctx.invoker.invoke(
            graph_run_id=gid,
            thread_id=tid,
            role_type="evaluator",
            provider_config_key=ctx.settings.kiloclaw_evaluator_config_key,
            input_payload=payload,
            iteration_index=int(state.get("iteration_index", 0)),
        )
        _log.info(
            "graph_run graph_run_id=%s stage=evaluator_invocation_finished elapsed_ms=%.1f",
            gid,
            (time.perf_counter() - t_ev) * 1000,
        )
        if inv.status == "failed":
            ctx.repo.save_role_invocation(inv)
            raise RoleInvocationFailed(
                phase="evaluator",
                graph_run_id=gid,
                thread_id=tid,
                detail=raw,
            )
        try:
            validate_role_output_for_persistence("evaluator", raw)
        except (ValidationError, ValueError) as e:
            pe = e.errors() if isinstance(e, ValidationError) else None
            msg = (
                "Persist-time validation failed"
                if isinstance(e, ValidationError)
                else str(e)
            )
            detail = contract_validation_failure(
                phase="evaluator",
                message=msg,
                pydantic_errors=pe,
            )
            _persist_invocation_failure(
                inv=inv,
                raw_detail=detail,
                phase="evaluator",
                graph_run_id=gid,
                thread_id=tid,
                repo=ctx.repo,
            )

        ctx.repo.save_role_invocation(inv)
        report = normalize_evaluator_output(
            raw,
            thread_id=tid,
            graph_run_id=gid,
            evaluator_invocation_id=inv.role_invocation_id,
            build_candidate_id=UUID(bcid),
        )
        bc_row = ctx.repo.get_build_candidate(UUID(bcid))
        if bc_row is not None:
            report = merge_gallery_strip_harness_checks(report, bc_row)
        report = report.model_copy(update={"raw_payload_json": raw})
        ctx.repo.save_evaluation_report(report)
        step_state = {
            **dict(state),
            "evaluation_report": {
                "status": report.status,
                "summary": report.summary,
                "issues": report.issues_json,
                "metrics": report.metrics_json,
                "artifacts": report.artifacts_json,
            },
            "evaluation_report_id": str(report.evaluation_report_id),
        }
        _save_checkpoint_with_event(
            ctx,
            CheckpointRecord(
                checkpoint_id=uuid4(),
                thread_id=tid,
                graph_run_id=gid,
                checkpoint_kind="post_step",
                state_json=step_state,
                context_compaction_json=None,
            ),
        )
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.EVALUATOR_INVOCATION_COMPLETED,
            {"evaluation_report_id": str(report.evaluation_report_id)},
        )
        return {
            "evaluation_report": step_state["evaluation_report"],
            "evaluation_report_id": str(report.evaluation_report_id),
        }

    def decision_router(state: GraphState) -> dict[str, Any]:
        gid = UUID(state["graph_run_id"])
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

        if status != "pass":
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
        if decision == "iterate":
            out["iteration_index"] = iteration + 1
        if interrupt_reason:
            out["interrupt_reason"] = interrupt_reason
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.DECISION_MADE,
            {"decision": decision, "interrupt_reason": interrupt_reason},
        )
        return out

    def staging_node(state: GraphState) -> dict[str, Any]:
        gid = UUID(state["graph_run_id"])
        tid = UUID(state["thread_id"])
        bcid_s = state.get("build_candidate_id")
        erid_s = state.get("evaluation_report_id")
        bsid_s = state.get("build_spec_id")
        if not bcid_s or not erid_s or not bsid_s:
            raise StagingIntegrityFailed(
                graph_run_id=gid,
                thread_id=tid,
                reason="staging_integrity",
                message="staging_node requires build_candidate_id, evaluation_report_id, build_spec_id",
                detail={"stage": "staging_node"},
            )
        bc = ctx.repo.get_build_candidate(UUID(bcid_s))
        ev = ctx.repo.get_evaluation_report(UUID(erid_s))
        if bc is None or ev is None:
            raise StagingIntegrityFailed(
                graph_run_id=gid,
                thread_id=tid,
                reason="persistence_error",
                message="could not load build_candidate or evaluation_report for staging",
                detail={
                    "build_candidate_id": bcid_s,
                    "evaluation_report_id": erid_s,
                },
            )
        if ev.status != "pass":
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.STAGING_SNAPSHOT_BLOCKED,
                {
                    "reason": "staging_integrity",
                    "error_kind": "staging_integrity",
                    "evaluation_status": ev.status,
                },
            )
            raise StagingIntegrityFailed(
                graph_run_id=gid,
                thread_id=tid,
                reason="staging_integrity",
                message="evaluation_report.status must be pass before staging snapshot",
                detail={"evaluation_status": ev.status},
            )
        try:
            validate_preview_integrity(bc, ev)
        except ValueError as e:
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.STAGING_SNAPSHOT_BLOCKED,
                {
                    "reason": "preview_integrity",
                    "error_kind": "staging_integrity",
                    "message": str(e),
                },
            )
            raise StagingIntegrityFailed(
                graph_run_id=gid,
                thread_id=tid,
                reason="preview_integrity",
                message=str(e),
                detail={"build_candidate_id": str(bc.build_candidate_id)},
            ) from e
        thread = ctx.repo.get_thread(tid)
        if thread is None:
            raise StagingIntegrityFailed(
                graph_run_id=gid,
                thread_id=tid,
                reason="persistence_error",
                message="thread not found for staging_snapshot",
                detail={"thread_id": str(tid)},
            )
        spec = ctx.repo.get_build_spec(UUID(bsid_s))
        payload = build_staging_snapshot_payload(
            build_candidate=bc,
            evaluation_report=ev,
            thread=thread,
            build_spec=spec,
        )
        t_st = time.perf_counter()
        _log.info(
            "graph_run graph_run_id=%s stage=staging_snapshot_creation_start elapsed_ms=0.0",
            gid,
        )
        ssid = uuid4()
        snap = StagingSnapshotRecord(
            staging_snapshot_id=ssid,
            thread_id=bc.thread_id,
            build_candidate_id=bc.build_candidate_id,
            graph_run_id=bc.graph_run_id,
            identity_id=thread.identity_id,
            snapshot_payload_json=payload,
            preview_url=bc.preview_url,
            status="review_ready",
        )
        ctx.repo.save_staging_snapshot(snap)
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.STAGING_SNAPSHOT_CREATED,
            {
                "staging_snapshot_id": str(ssid),
                "graph_run_id": str(gid),
                "thread_id": str(tid),
                "build_candidate_id": str(bc.build_candidate_id),
                "reason": "snapshot_persisted",
                "review_ready": True,
                "preview_url": bc.preview_url,
            },
        )
        _log.info(
            "graph_run graph_run_id=%s stage=staging_snapshot_creation_done staging_snapshot_id=%s elapsed_ms=%.1f",
            gid,
            ssid,
            (time.perf_counter() - t_st) * 1000,
        )
        return {"staging_snapshot_id": str(ssid), "status": "completed"}

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
    t_run = time.perf_counter()
    _log.info(
        "run_graph graph_run_id=%s stage=langgraph_invoke_start elapsed_ms=0.0",
        gid0,
    )
    try:
        final = app.invoke(base)
    except RoleInvocationFailed as e:
        if gid0:
            gid_u = UUID(str(gid0))
            tid_u = e.thread_id
            ek = error_kind_from_detail(e.detail) or "role_invocation"
            _save_checkpoint_with_event(
                ctx,
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
                ctx,
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
            if tid_s:
                tid_u = UUID(str(tid_s))
                _save_checkpoint_with_event(
                    ctx,
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
                    ),
                )
                append_graph_run_event(
                    repo,
                    gid_u,
                    RunEventType.GRAPH_RUN_FAILED,
                    {"error_kind": "graph_error"},
                )
            repo.update_graph_run_status(
                gid_u,
                "failed",
                datetime.now(timezone.utc).isoformat(),
            )
        raise
    assert isinstance(final, dict)
    gid = final.get("graph_run_id")
    if gid:
        tid_s = final.get("thread_id")
        if tid_s:
            gid_u = UUID(gid)
            post = CheckpointRecord(
                checkpoint_id=uuid4(),
                thread_id=UUID(tid_s),
                graph_run_id=gid_u,
                checkpoint_kind="post_role",
                state_json=dict(final),
                context_compaction_json=None,
            )
            _save_checkpoint_with_event(ctx, post)
            repo.update_thread_current_checkpoint(UUID(tid_s), post.checkpoint_id)
        ended = datetime.now(timezone.utc).isoformat()
        repo.update_graph_run_status(UUID(gid), "completed", ended)
        repo.attach_run_snapshot(UUID(gid), dict(final))
        append_graph_run_event(
            repo,
            UUID(gid),
            RunEventType.GRAPH_RUN_COMPLETED,
            {},
        )
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
            Literal["prompt", "resume", "schedule", "system"], trigger_type
        ),
        status="running",
    )
    repo.save_graph_run(gr)
    append_graph_run_event(repo, UUID(gid), RunEventType.GRAPH_RUN_STARTED, {})
    _log.info(
        "persist_graph_run_start graph_run_id=%s thread_id=%s stage=graph_run_persisted elapsed_ms=%.1f",
        gid,
        tid,
        (time.perf_counter() - t0) * 1000,
    )
    _ = event_input
    return tid, gid
