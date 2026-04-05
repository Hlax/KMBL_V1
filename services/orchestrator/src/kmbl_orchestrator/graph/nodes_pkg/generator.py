"""generator_node — invoke the generator role and persist the build candidate."""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from kmbl_orchestrator.contracts.normalized_errors import contract_validation_failure
from kmbl_orchestrator.contracts.persistence_validate import (
    validate_role_output_for_persistence,
)
from kmbl_orchestrator.domain import CheckpointRecord
from kmbl_orchestrator.errors import KiloclawRoleInvocationForbiddenError, RoleInvocationFailed
from kmbl_orchestrator.graph.helpers import (
    _apply_html_blocks_to_candidate,
    _iteration_plan_extras_from_ws_facts,
    _persist_invocation_failure,
    _save_checkpoint_with_event,
)
from kmbl_orchestrator.graph.state import GraphState
from kmbl_orchestrator.normalize import normalize_generator_output
from kmbl_orchestrator.runtime.cool_generation_lane import (
    annotate_cool_lane_generator_compliance,
    cool_generation_lane_active,
    summarize_execution_contract_for_generator,
)
from kmbl_orchestrator.runtime.kilo_model_routing import (
    ImageRouteBudgetExceededError,
    ImageRouteConfigurationError,
    select_generator_provider_config,
)
from kmbl_orchestrator.runtime.iteration_plan import build_iteration_plan_for_generator
from kmbl_orchestrator.runtime.interrupt_checks import raise_if_interrupt_requested
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event
from kmbl_orchestrator.staging.facts import (
    build_working_staging_facts,
    working_staging_facts_to_payload,
)
from kmbl_orchestrator.staging.integrity import (
    StaticVerticalBundleRejected,
    validate_generator_output_for_candidate,
    validate_static_frontend_bundle_requirement,
)

if TYPE_CHECKING:
    from kmbl_orchestrator.graph.app import GraphContext

_log = logging.getLogger(__name__)


def generator_node(ctx: "GraphContext", state: GraphState) -> dict[str, Any]:
    """Invoke the generator role and persist the resulting build candidate."""
    gid = UUID(state["graph_run_id"])
    tid = UUID(state["thread_id"])
    raise_if_interrupt_requested(ctx.repo, gid, tid)
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
    _save_checkpoint_with_event(ctx.repo, cp0)
    append_graph_run_event(ctx.repo, gid, RunEventType.GENERATOR_INVOCATION_STARTED, {}, thread_id=tid)
    _log.info(
        "graph_run graph_run_id=%s stage=generator_invocation_start elapsed_ms=0.0",
        gid,
    )

    iteration = int(state.get("iteration_index", 0))
    feedback: Any = None
    if iteration > 0:
        feedback = state.get("evaluation_report")

    ws = ctx.repo.get_working_staging_for_thread(tid)
    ws_facts: dict[str, Any] | None = None

    # On iteration > 0, build facts from the current build_candidate in state
    # so generator sees fresh context from this run's candidate
    ev_status = feedback.get("status") if isinstance(feedback, dict) else None
    ev_issues = feedback.get("issues") if isinstance(feedback, dict) else None

    if iteration > 0 and state.get("build_candidate"):
        # Build facts from in-progress candidate (not stale DB state)
        candidate = state.get("build_candidate") or {}
        candidate_artifacts = candidate.get("artifact_outputs", [])
        artifact_count = len(candidate_artifacts)
        has_html = any(
            a.get("artifact_type") == "static_file" and 
            str(a.get("path", "")).endswith((".html", ".htm"))
            for a in candidate_artifacts
        )
        facts = build_working_staging_facts(
            ws,
            checkpoint_count=0,
            latest_checkpoint_revision=None,
            latest_checkpoint_trigger=None,
            evaluator_status=ev_status,
            evaluator_issues=ev_issues,
            patches_since_rebuild=iteration,
            stagnation_count=(ws.stagnation_count if ws is not None else 0),
        )
        # Override with fresh candidate info
        facts.artifact_inventory.total_count = artifact_count
        facts.artifact_inventory.has_previewable_html = has_html
        facts.iteration_context = {
            "iteration_index": iteration,
            "previous_status": ev_status,
            "issue_count": len(ev_issues) if ev_issues else 0,
        }
        ws_facts = working_staging_facts_to_payload(facts)
    elif ws is not None:
        checkpoints = ctx.repo.list_staging_checkpoints(ws.working_staging_id, limit=5)
        latest_cp = checkpoints[0] if checkpoints else None

        facts = build_working_staging_facts(
            ws,
            checkpoint_count=len(checkpoints),
            latest_checkpoint_revision=latest_cp.revision_at_checkpoint if latest_cp else None,
            latest_checkpoint_trigger=latest_cp.trigger if latest_cp else None,
            evaluator_status=ev_status,
            evaluator_issues=ev_issues,
            patches_since_rebuild=(ws.revision - (ws.last_rebuild_revision or 0)),
            stagnation_count=ws.stagnation_count,
        )
        ws_facts = working_staging_facts_to_payload(facts)

    st_plan, pr_plan = _iteration_plan_extras_from_ws_facts(ws_facts)
    iteration_plan = (
        build_iteration_plan_for_generator(
            feedback,
            stagnation_count=st_plan,
            pressure_recommendation=pr_plan,
        )
        if iteration > 0 and isinstance(feedback, dict)
        else None
    )

    ei0 = state.get("event_input") if isinstance(state.get("event_input"), dict) else {}
    bs0 = state.get("build_spec") if isinstance(state.get("build_spec"), dict) else {}
    payload = {
        "graph_run_id": str(gid),
        "thread_id": state["thread_id"],
        "build_spec": state.get("build_spec") or {},
        "current_working_state": state.get("current_state") or {},
        "iteration_feedback": feedback,
        "iteration_plan": iteration_plan,
        "event_input": state.get("event_input") or {},
        "working_staging_facts": ws_facts,
        # Fix 1: identity_brief injected directly — survives planner reinterpretation
        "identity_brief": state.get("identity_brief"),
        # Structured identity profile: themes, tone, visual_tendencies, content_types,
        # complexity, notable_entities — enables identity-shaped generation.
        "structured_identity": state.get("structured_identity"),
        # Cool lane: compact execution surface + explicit flag (see docs/PLANNER_GENERATOR_COOL_LANE.md)
        "cool_generation_lane_active": cool_generation_lane_active(ei0, bs0),
        "kmbl_execution_contract": summarize_execution_contract_for_generator(bs0),
        # Fix 3: retry_context carries orchestrator-selected direction on iterations
        # Generator must use retry_context.retry_direction to determine approach
    }
    # Derive spatial translation hints from structured identity visual tendencies
    si_payload = state.get("structured_identity")
    if si_payload and isinstance(si_payload, dict):
        from kmbl_orchestrator.identity.profile import derive_spatial_translation_hints
        visual_t = si_payload.get("visual_tendencies") or []
        hints = derive_spatial_translation_hints(visual_t)
        if hints:
            payload["spatial_translation_hints"] = hints
    # Merge retry_context into iteration_plan when present.
    # In-graph retries: iteration > 0 (evaluator feedback from prior step).
    # Autonomous loop ticks: each run_graph starts at iteration_index 0, but the loop
    # still passes orchestrator retry_context — merge when trigger_type is autonomous_loop.
    rc = state.get("retry_context") or {}
    should_merge_retry_context = bool(rc) and (
        iteration > 0
        or str(state.get("trigger_type") or "") == "autonomous_loop"
    )
    if should_merge_retry_context:
        if payload["iteration_plan"] is None:
            payload["iteration_plan"] = {}
        payload["iteration_plan"] = {**payload["iteration_plan"], **rc}
    try:
        payload_json_chars = len(json.dumps(payload, ensure_ascii=False, default=str))
    except Exception:
        payload_json_chars = -1
    _log.info(
        "generator_payload graph_run_id=%s iteration_index=%s payload_json_chars=%s",
        gid,
        iteration,
        payload_json_chars,
    )
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
    except Exception as e:
        # Catch any other routing configuration errors
        _log.error(
            "generator routing failed unexpectedly: exc_type=%s message=%s",
            type(e).__name__,
            str(e)[:200],
        )
        detail = contract_validation_failure(
            phase="generator",
            message=f"generator routing configuration error: {type(e).__name__}: {e!s}",
            pydantic_errors=None,
        )
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.CONTRACT_WARNING,
            {
                "role": "generator",
                "phase": "routing_configuration",
                "error_type": type(e).__name__,
                "error_message": str(e)[:500],
            },
            thread_id=tid,
        )
        raise RoleInvocationFailed(
            phase="generator",
            graph_run_id=gid,
            thread_id=tid,
            detail=detail,
        ) from e
    t_gen = time.perf_counter()
    _log.info(
        "generator_invoke graph_run_id=%s iteration_index=%s provider_config_key=%s payload_json_chars=%s",
        gid,
        iteration,
        gen_key,
        payload_json_chars,
    )
    try:
        inv, raw = ctx.invoker.invoke(
            graph_run_id=gid,
            thread_id=tid,
            role_type="generator",
            provider_config_key=gen_key,
            input_payload=payload,
            iteration_index=iteration,
            routing_metadata=routing_meta,
        )
    except KiloclawRoleInvocationForbiddenError as e:
        raise RoleInvocationFailed(
            phase="generator",
            graph_run_id=gid,
            thread_id=tid,
            detail={
                "error_kind": "transport_forbidden",
                "message": str(e),
                "operator_hint": e.operator_hint,
            },
        ) from e
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
    raw = annotate_cool_lane_generator_compliance(
        raw,
        build_spec=state.get("build_spec") if isinstance(state.get("build_spec"), dict) else {},
        event_input=state.get("event_input") if isinstance(state.get("event_input"), dict) else {},
    )
    try:
        validate_generator_output_for_candidate(raw)
        validate_static_frontend_bundle_requirement(
            state.get("build_spec") if isinstance(state.get("build_spec"), dict) else {},
            state.get("event_input") if isinstance(state.get("event_input"), dict) else {},
            raw,
        )
    except ValueError as e:
        xdetails: dict[str, Any] = {"static_frontend_bundle_gate": True}
        if isinstance(e, StaticVerticalBundleRejected) and getattr(e, "output_class", None):
            xdetails["output_class"] = e.output_class
        detail = contract_validation_failure(
            phase="generator",
            message=str(e),
            pydantic_errors=None,
            extra_details=xdetails,
        )
        ev_payload: dict[str, Any] = {
            "message": str(e)[:800],
            "error_kind": "static_frontend_bundle_requirement",
        }
        if isinstance(e, StaticVerticalBundleRejected) and getattr(e, "output_class", None):
            ev_payload["output_class"] = e.output_class
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.GENERATOR_STATIC_BUNDLE_REJECTED,
            ev_payload,
            thread_id=tid,
        )
        _persist_invocation_failure(
            inv=inv,
            raw_detail=detail,
            phase="generator",
            graph_run_id=gid,
            thread_id=tid,
            repo=ctx.repo,
        )

    cf = raw.get("contract_failure")
    if isinstance(cf, dict) and isinstance(cf.get("code"), str) and cf["code"].strip():
        if isinstance(cf.get("message"), str) and cf["message"].strip():
            detail = {
                "status": "failed",
                "error_kind": "contract_failure",
                "message": cf["message"],
                "details": {"code": cf["code"], "contract_failure": cf},
            }
            _persist_invocation_failure(
                inv=inv,
                raw_detail=detail,
                phase="generator",
                graph_run_id=gid,
                thread_id=tid,
                repo=ctx.repo,
            )

    persist_validation_failed = False
    try:
        validate_role_output_for_persistence("generator", raw)
    except (ValidationError, ValueError) as e:
        persist_validation_failed = True
        _log.warning(
            "generator persist-time validation issue (non-fatal, normalization proceeds): %s", e,
        )
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.CONTRACT_WARNING,
            {
                "role": "generator",
                "phase": "persist_validation",
                "severity": "degraded",
                "warning": str(e)[:500],
                "message": "generator output failed persist-time validation; normalization will attempt rescue",
            },
            thread_id=tid,
        )

    ctx.repo.save_role_invocation(inv)

    # Get identity_id from state for image generation context
    iid_raw = state.get("identity_id")
    identity_id: UUID | None = None
    if iid_raw:
        try:
            identity_id = UUID(str(iid_raw))
        except (ValueError, TypeError):
            pass

    cand = normalize_generator_output(
        raw,
        thread_id=tid,
        graph_run_id=gid,
        generator_invocation_id=inv.role_invocation_id,
        build_spec_id=UUID(bsid),
        identity_id=identity_id,
        enable_image_generation=ctx.settings.habitat_image_generation_enabled,
    )
    # Track persist_validation_failed in candidate metadata for downstream awareness
    if persist_validation_failed:
        cand = cand.model_copy(
            update={
                "raw_payload_json": {
                    **(cand.raw_payload_json or {}),
                    "_persist_validation_failed": True,
                }
            }
        )
    # Emit normalization enrichment event for informational bookkeeping (not rescue)
    enrichment_paths = (cand.raw_payload_json or {}).get("_normalization_enrichments")
    if enrichment_paths:
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.NORMALIZATION_ENRICHMENT,
            {
                "enrichment_paths": enrichment_paths,
                "build_candidate_id": str(cand.build_candidate_id),
            },
            thread_id=tid,
        )
        _log.debug(
            "graph_run graph_run_id=%s normalization_enrichments=%s",
            gid,
            enrichment_paths,
        )
    # Emit normalization rescue event only for genuine recovery/correction
    rescue_paths = (cand.raw_payload_json or {}).get("_normalization_rescues")
    if rescue_paths:
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.NORMALIZATION_RESCUE,
            {
                "rescue_paths": rescue_paths,
                "build_candidate_id": str(cand.build_candidate_id),
            },
            thread_id=tid,
        )
        inv = inv.model_copy(
            update={
                "routing_metadata_json": {
                    **dict(inv.routing_metadata_json or {}),
                    "normalization_rescue": True,
                    "normalization_rescue_paths": rescue_paths,
                }
            }
        )
        ctx.repo.save_role_invocation(inv)
        _log.info(
            "graph_run graph_run_id=%s normalization_rescues=%s",
            gid,
            rescue_paths,
        )

    # Apply html_block_v1 artifacts to the current working staging (if any)
    cand = _apply_html_blocks_to_candidate(ctx.repo, cand, tid)

    # Sequential PostgREST writes — no cross-call rollback on Supabase (see RPC helpers for atomicity).
    ctx.repo.save_build_candidate(cand)
    block_anchors = (cand.working_state_patch_json or {}).get("block_preview_anchors") or []
    step_state = {
        **dict(state),
        "build_candidate": {
            "proposed_changes": raw.get("proposed_changes"),
            "artifact_outputs": raw.get("artifact_outputs"),
            "updated_state": raw.get("updated_state"),
            "sandbox_ref": raw.get("sandbox_ref"),
            "preview_url": raw.get("preview_url"),
            "block_anchors": block_anchors if block_anchors else None,
            "execution_acknowledgment": raw.get("execution_acknowledgment"),
            "_kmbl_compliance": raw.get("_kmbl_compliance"),
        },
        "build_candidate_id": str(cand.build_candidate_id),
        "current_state": raw.get("updated_state") or state.get("current_state") or {},
    }
    _save_checkpoint_with_event(
        ctx.repo,
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
