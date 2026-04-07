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
from kmbl_orchestrator.runtime.habitat_strategy import (
    effective_habitat_strategy_for_iteration,
)
from kmbl_orchestrator.runtime.interactive_lane_context import build_interactive_lane_context
from kmbl_orchestrator.runtime.interrupt_checks import raise_if_interrupt_requested
from kmbl_orchestrator.runtime.payload_budget_governor_v1 import (
    apply_payload_budget_governor_v1,
    merge_governor_report_into_telemetry,
)
from kmbl_orchestrator.runtime.payload_telemetry_v1 import build_payload_telemetry_v1
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event
from kmbl_orchestrator.runtime.static_vertical_invariants import (
    is_interactive_frontend_vertical,
    is_manifest_first_bundle_vertical,
)
from kmbl_orchestrator.runtime.workspace_ingest import (
    WorkspaceIngestError,
    compute_workspace_ingest_preflight,
    ingest_workspace_manifest_if_present,
    workspace_ingest_not_attempted_reason,
    workspace_ingest_should_attempt,
)
from kmbl_orchestrator.runtime.artifact_snippet_extract import extract_evaluator_snippets
from kmbl_orchestrator.runtime.artifact_inspector_v2 import build_build_candidate_summary_v2
from kmbl_orchestrator.runtime.evaluator_snippet_policy_v1 import (
    should_prebuild_snippets_for_graph_state,
)
from kmbl_orchestrator.runtime.generator_wire_compact_v1 import (
    shape_generator_invocation_output_payload,
    wire_compaction_routing_marker,
)
from kmbl_orchestrator.runtime.build_candidate_summary_v1 import (
    build_build_candidate_summary_v1,
    build_slim_build_candidate_state_dict,
    merge_summary_into_raw_payload,
)
from kmbl_orchestrator.runtime.workspace_paths import build_workspace_context_for_generator
from kmbl_orchestrator.runtime.workspace_paths import run_workspace_directory
from kmbl_orchestrator.runtime.workspace_retention import (
    ensure_clean_workspace,
    mark_workspace_parse_failed,
)
from kmbl_orchestrator.runtime.demo_preview_grounding import sanitize_feedback_for_generator
from kmbl_orchestrator.runtime.working_staging_read import (
    get_working_staging_for_thread_resilient,
)
from kmbl_orchestrator.staging.facts import (
    build_working_staging_facts,
    working_staging_facts_to_payload,
)
from kmbl_orchestrator.staging.integrity import (
    StaticVerticalBundleRejected,
    scan_interactive_bundle_missing_script_evidence,
    scan_interactive_bundle_preview_risks,
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
        # Strip non-actionable grounding issues before any further processing.
        # For grounding-only partials this leaves issues=[] (build was quality-pass).
        # For mixed partials this removes only the grounding issue, keeping real defects.
        feedback = sanitize_feedback_for_generator(feedback)
        # Truncate evaluator issues to avoid token bloat in generator retry context.
        # Keep the top 5 most relevant issues (order preserved from evaluator priority).
        if isinstance(feedback, dict) and isinstance(feedback.get("issues"), list):
            if len(feedback["issues"]) > 5:
                feedback = {**feedback, "issues": feedback["issues"][:5]}

    ws = get_working_staging_for_thread_resilient(
        ctx.repo,
        tid,
        graph_run_id=gid,
        phase="generator",
        iteration_index=iteration,
    )
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
            str(a.get("path", "")).lower().endswith((".html", ".htm")) for a in candidate_artifacts
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

    heff = effective_habitat_strategy_for_iteration(
        event_input=state.get("event_input") or {},
        build_spec=state.get("build_spec") or {},
        iteration_index=iteration,
    )
    if heff in ("fresh_start", "rebuild_informed") and iteration == 0:
        ws_facts = {
            "orchestrator_note": "prior_live_habitat_cleared",
            "habitat_strategy_effective": heff,
            "suppress_stale_workspace_snapshot": True,
        }

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

    # Workspace isolation: ensure a clean per-run directory so stale artifacts from
    # prior (possibly failed) runs never leak into this generation.
    _run_ws_dir = run_workspace_directory(ctx.settings, tid, gid)
    ensure_clean_workspace(_run_ws_dir)

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
        # surface_type: tells generator what output shape to produce
        # (static_html vs webgl_experience). Derived from experience_mode by planner.
        "surface_type": bs0.get("surface_type", "static_html"),
        # Orchestrator-enforced habitat semantics (OpenClaw generator should not trust stale canvas)
        "kmbl_habitat_runtime": {
            "effective_strategy": heff,
            "suppress_prior_working_surface": heff
            in ("fresh_start", "rebuild_informed")
            and iteration == 0,
        },
        # Local-build lane: resolved workspace root + per-run directory (outside repo by default).
        "workspace_context": build_workspace_context_for_generator(ctx.settings, tid, gid),
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
    if iteration > 0:
        prior_v2 = state.get("last_build_candidate_summary_v2")
        prior_v1 = state.get("last_build_candidate_summary_v1")
        if isinstance(prior_v2, dict):
            payload["kmbl_prior_build_candidate_summary_v2"] = prior_v2
        if isinstance(prior_v1, dict):
            payload["kmbl_prior_build_candidate_summary_v1"] = prior_v1
    if is_interactive_frontend_vertical(bs0, ei0):
        from kmbl_orchestrator.runtime.reference_library import attach_reference_cards_to_lane_context

        _ilc = build_interactive_lane_context(bs0, ei0)
        _ilc = attach_reference_cards_to_lane_context(
            _ilc, bs0, ei0, graph_run_id=str(gid)
        )
        payload["kmbl_interactive_lane_context"] = _ilc
        payload["kmbl_reference_patterns"] = _ilc.get("reference_patterns") or []
        payload["kmbl_library_compliance_hints"] = _ilc.get("library_compliance_hints") or []
        payload["kmbl_implementation_reference_cards"] = _ilc.get("implementation_reference_cards") or []
        payload["kmbl_inspiration_reference_cards"] = _ilc.get("inspiration_reference_cards") or []
        payload["kmbl_planner_observed_reference_cards"] = _ilc.get(
            "planner_observed_reference_cards"
        ) or []
        payload["kmbl_reference_selection_meta"] = _ilc.get("reference_selection_meta")
        payload["kmbl_reference_library_version"] = _ilc.get("reference_library_version")
    chars_saved_iteration = 0
    if iteration > 0:
        from kmbl_orchestrator.runtime.generator_iteration_compact_v1 import (
            apply_iteration_compaction,
        )

        chars_saved_iteration = apply_iteration_compaction(payload, iteration)
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
    payload, gov_rep_g = apply_payload_budget_governor_v1("generator", payload)
    try:
        payload_json_chars = len(json.dumps(payload, ensure_ascii=False, default=str))
    except Exception:
        payload_json_chars = -1
    t_gen = time.perf_counter()
    _log.info(
        "generator_invoke graph_run_id=%s iteration_index=%s provider_config_key=%s payload_json_chars=%s",
        gid,
        iteration,
        gen_key,
        payload_json_chars,
    )
    tel_g = build_payload_telemetry_v1("generator", payload)
    if iteration > 0 and chars_saved_iteration:
        tel_g["chars_saved_from_iteration_compaction"] = chars_saved_iteration
    tel_g = merge_governor_report_into_telemetry(tel_g, gov_rep_g)
    routing_meta = {**dict(routing_meta or {}), "kmbl_payload_telemetry_v1": tel_g}
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
        mark_workspace_parse_failed(_run_ws_dir)
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
    bs_ing = state.get("build_spec") if isinstance(state.get("build_spec"), dict) else {}
    ei_ing = state.get("event_input") if isinstance(state.get("event_input"), dict) else {}
    manifest_first = bool(
        getattr(ctx.settings, "kmbl_manifest_first_static_vertical", False),
    ) and is_manifest_first_bundle_vertical(bs_ing, ei_ing)
    ingest_role = (
        "interactive_frontend_app_v1"
        if is_interactive_frontend_vertical(bs_ing, ei_ing)
        else "static_frontend_file_v1"
    )
    if manifest_first:
        na = workspace_ingest_not_attempted_reason(raw)
        if na is not None:
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.WORKSPACE_INGEST_NOT_ATTEMPTED,
                {**na, "manifest_first": True},
                thread_id=tid,
            )
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.MANIFEST_FIRST_VIOLATION,
                {
                    "error_kind": "manifest_first_missing_workspace",
                    "phase": "pre_ingest",
                    "reason": na.get("code"),
                },
                thread_id=tid,
            )
            detail = contract_validation_failure(
                phase="generator",
                message="manifest-first static vertical requires workspace_manifest_v1 with files and sandbox_ref",
                pydantic_errors=None,
                extra_details={
                    "error_kind": "manifest_first_missing_workspace",
                    "workspace_ingest": na,
                },
            )
            _persist_invocation_failure(
                inv=inv,
                raw_detail=detail,
                phase="generator",
                graph_run_id=gid,
                thread_id=tid,
                repo=ctx.repo,
            )
            raise RoleInvocationFailed(
                phase="generator",
                graph_run_id=gid,
                thread_id=tid,
                detail={
                    "error_kind": "manifest_first_missing_workspace",
                    "workspace_ingest": na,
                },
            )
    if workspace_ingest_should_attempt(raw):
        wm_pf = raw.get("workspace_manifest_v1")
        sr_pf = raw.get("sandbox_ref")
        preflight: dict[str, Any] = {}
        if isinstance(wm_pf, dict) and isinstance(sr_pf, str) and sr_pf.strip():
            preflight = compute_workspace_ingest_preflight(
                ctx.settings,
                tid,
                gid,
                sr_pf.strip(),
                wm_pf,
            )
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.WORKSPACE_INGEST_STARTED,
            preflight,
            thread_id=tid,
        )
    try:
        raw, ingest_stats, inline_skip = ingest_workspace_manifest_if_present(
            raw,
            settings=ctx.settings,
            thread_id=tid,
            graph_run_id=gid,
            ingested_artifact_role=ingest_role,
        )
    except WorkspaceIngestError as e:
        mark_workspace_parse_failed(_run_ws_dir)
        fail_ev: dict[str, Any] = {"message": str(e)[:800]}
        if e.details:
            fail_ev["ingest_details"] = e.details
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.WORKSPACE_INGEST_FAILED,
            fail_ev,
            thread_id=tid,
        )
        detail = contract_validation_failure(
            phase="generator",
            message=str(e),
            pydantic_errors=None,
            extra_details={"workspace_ingest": True},
        )
        _persist_invocation_failure(
            inv=inv,
            raw_detail=detail,
            phase="generator",
            graph_run_id=gid,
            thread_id=tid,
            repo=ctx.repo,
        )
        raise RoleInvocationFailed(
            phase="generator",
            graph_run_id=gid,
            thread_id=tid,
            detail={"error_kind": "workspace_ingest", "message": str(e)},
        ) from e
    if manifest_first and inline_skip == "inline_html":
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.WORKSPACE_INGEST_SKIPPED_INLINE_HTML,
            {"reason": "inline_html", "manifest_first": True},
            thread_id=tid,
        )
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.MANIFEST_FIRST_VIOLATION,
            {
                "error_kind": "manifest_first_ingest_skipped_or_empty",
                "phase": "post_ingest",
                "reason": "inline_html",
            },
            thread_id=tid,
        )
        detail = contract_validation_failure(
            phase="generator",
            message="manifest-first static vertical forbids inline HTML overriding workspace ingest",
            pydantic_errors=None,
            extra_details={
                "error_kind": "manifest_first_ingest_skipped_or_empty",
                "inline_skip": inline_skip,
            },
        )
        _persist_invocation_failure(
            inv=inv,
            raw_detail=detail,
            phase="generator",
            graph_run_id=gid,
            thread_id=tid,
            repo=ctx.repo,
        )
        raise RoleInvocationFailed(
            phase="generator",
            graph_run_id=gid,
            thread_id=tid,
            detail={
                "error_kind": "manifest_first_ingest_skipped_or_empty",
                "inline_skip": inline_skip,
            },
        )
    if manifest_first and ingest_stats is None and workspace_ingest_should_attempt(raw):
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.MANIFEST_FIRST_VIOLATION,
            {
                "error_kind": "manifest_first_ingest_skipped_or_empty",
                "phase": "post_ingest",
                "reason": "unexpected_empty_ingest",
            },
            thread_id=tid,
        )
        detail = contract_validation_failure(
            phase="generator",
            message="manifest-first static vertical requires successful workspace ingest",
            pydantic_errors=None,
            extra_details={"error_kind": "manifest_first_ingest_skipped_or_empty"},
        )
        _persist_invocation_failure(
            inv=inv,
            raw_detail=detail,
            phase="generator",
            graph_run_id=gid,
            thread_id=tid,
            repo=ctx.repo,
        )
        raise RoleInvocationFailed(
            phase="generator",
            graph_run_id=gid,
            thread_id=tid,
            detail={"error_kind": "manifest_first_ingest_skipped_or_empty"},
        )
    if ingest_stats:
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.WORKSPACE_INGEST_COMPLETED,
            ingest_stats,
            thread_id=tid,
        )
    raw["_kmbl_frontend_artifact_role"] = ingest_role
    try:
        validate_generator_output_for_candidate(raw)
        validate_static_frontend_bundle_requirement(
            state.get("build_spec") if isinstance(state.get("build_spec"), dict) else {},
            state.get("event_input") if isinstance(state.get("event_input"), dict) else {},
            raw,
        )
        bs_v = state.get("build_spec") if isinstance(state.get("build_spec"), dict) else {}
        ei_v = state.get("event_input") if isinstance(state.get("event_input"), dict) else {}
        if is_interactive_frontend_vertical(bs_v, ei_v):
            ao_risk = raw.get("artifact_outputs")
            risks = scan_interactive_bundle_preview_risks(ao_risk if isinstance(ao_risk, list) else [])
            if risks:
                append_graph_run_event(
                    ctx.repo,
                    gid,
                    RunEventType.CONTRACT_WARNING,
                    {
                        "role": "generator",
                        "phase": "interactive_lane_preview_risks",
                        "risks": risks,
                    },
                    thread_id=tid,
                )
            miss = scan_interactive_bundle_missing_script_evidence(
                ao_risk if isinstance(ao_risk, list) else [],
            )
            if miss is not None:
                append_graph_run_event(
                    ctx.repo,
                    gid,
                    RunEventType.CONTRACT_WARNING,
                    {
                        "role": "generator",
                        "phase": "interactive_lane_script_evidence",
                        **miss,
                    },
                    thread_id=tid,
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

    debug_raw = bool(
        getattr(ctx.settings, "kmbl_persist_raw_generator_output_for_debug", False),
    )
    if debug_raw:
        _log.warning(
            "graph_run graph_run_id=%s generator kmbl_persist_raw_generator_output_for_debug=true "
            "— persisting full model output bodies on role_invocation rows",
            gid,
        )
    # Workspace-first: when workspace_manifest_v1 + sandbox_ref are present in the
    # generator output, the workspace is authoritative.  Skip persisting full inline
    # artifact_outputs content on the wire — metadata + snippet suffice.
    _ws_first = bool(
        isinstance(raw.get("workspace_manifest_v1"), dict)
        and isinstance(raw.get("sandbox_ref"), str)
        and raw.get("sandbox_ref", "").strip()
    )
    persist_out, persist_shape = shape_generator_invocation_output_payload(
        raw,
        persist_raw_for_debug=debug_raw,
        post_normalization=False,
        workspace_first=_ws_first,
    )
    rm_first = dict(inv.routing_metadata_json or {})
    rm_first["kmbl_generator_persistence_shape_v1"] = persist_shape
    wc_meta = persist_shape.get("wire_compaction")
    rm_first["kmbl_generator_wire_compaction_v1"] = wire_compaction_routing_marker(
        persist_raw_for_debug=debug_raw,
        wire_meta=wc_meta if isinstance(wc_meta, dict) else None,
    )
    inv = inv.model_copy(
        update={
            "output_payload_json": persist_out,
            "routing_metadata_json": rm_first,
        },
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
    cand = _apply_html_blocks_to_candidate(ctx.repo, cand, tid, graph_run_id=gid)

    refs = list(cand.artifact_refs_json or [])
    prior_sum = state.get("last_build_candidate_summary_v2") or state.get("last_build_candidate_summary_v1")
    gen_notes = raw.get("generator_self_summary") if isinstance(raw.get("generator_self_summary"), str) else None
    summary_v1 = build_build_candidate_summary_v1(
        refs,
        build_spec=bs0,
        event_input=ei0,
        prior_summary=prior_sum if isinstance(prior_sum, dict) else None,
        generator_notes=gen_notes,
    )
    summary_v2 = build_build_candidate_summary_v2(
        refs,
        build_spec=bs0,
        event_input=ei0,
        prior_summary=prior_sum if isinstance(prior_sum, dict) else None,
        generator_notes=gen_notes,
        generator_raw=raw,
    )
    persist_out2, persist_shape2 = shape_generator_invocation_output_payload(
        raw,
        persist_raw_for_debug=debug_raw,
        post_normalization=True,
        workspace_first=_ws_first,
    )
    rm_inv = dict(inv.routing_metadata_json or {})
    merged_shape = {**(rm_inv.get("kmbl_generator_persistence_shape_v1") or {}), **persist_shape2}
    rm_inv["kmbl_generator_persistence_shape_v1"] = merged_shape
    wc_meta2 = persist_shape2.get("wire_compaction")
    rm_inv["kmbl_generator_wire_compaction_v1"] = wire_compaction_routing_marker(
        persist_raw_for_debug=debug_raw,
        wire_meta=wc_meta2 if isinstance(wc_meta2, dict) else None,
    )
    inv = inv.model_copy(
        update={
            "output_payload_json": persist_out2,
            "routing_metadata_json": rm_inv,
        },
    )
    ctx.repo.save_role_invocation(inv)
    state_compact, _ = shape_generator_invocation_output_payload(
        raw,
        persist_raw_for_debug=False,
        post_normalization=True,
        workspace_first=_ws_first,
    )
    raw.clear()
    raw.update(state_compact)

    preview_hint = cand.preview_url or raw.get("preview_url")
    if should_prebuild_snippets_for_graph_state(
        summary_v2=summary_v2,
        preview_url_hint=str(preview_hint) if preview_hint else "",
    ):
        snippets_v1 = extract_evaluator_snippets(refs)
    else:
        snippets_v1 = None
    cand = cand.model_copy(
        update={
            "raw_payload_json": merge_summary_into_raw_payload(
                cand.raw_payload_json, summary_v1, summary_v2=summary_v2
            ),
        }
    )

    # Sequential PostgREST writes — no cross-call rollback on Supabase (see RPC helpers for atomicity).
    ctx.repo.save_build_candidate(cand)
    block_anchors = (cand.working_state_patch_json or {}).get("block_preview_anchors") or []
    raw_for_slim = dict(raw)
    if block_anchors:
        raw_for_slim["block_anchors"] = block_anchors
    slim_candidate = build_slim_build_candidate_state_dict(
        raw_generator=raw_for_slim,
        summary=summary_v1,
        snippets=snippets_v1,
        full_artifacts=refs,
        summary_v2=summary_v2,
    )
    step_state = {
        **dict(state),
        "build_candidate": slim_candidate,
        "build_candidate_id": str(cand.build_candidate_id),
        "current_state": raw.get("updated_state") or state.get("current_state") or {},
        "last_build_candidate_summary_v1": summary_v1,
        "last_build_candidate_summary_v2": summary_v2,
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

    # --- Habitat lifecycle: register candidate_preview materialization ---
    try:
        from kmbl_orchestrator.runtime.habitat_lifecycle import register_materialization

        cp_manifest = register_materialization(
            thread_id=tid,
            local_path=f"candidate_preview/{tid}/{cand.build_candidate_id}",
            materialization_kind="candidate_preview",
            graph_run_id=gid,
            revision_id=cand.build_candidate_id,
            can_rehydrate_from_persistence=True,
        )
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.HABITAT_MATERIALIZED,
            {
                "manifest_id": str(cp_manifest.manifest_id),
                "materialization_kind": "candidate_preview",
                "thread_id": str(tid),
                "build_candidate_id": str(cand.build_candidate_id),
            },
            thread_id=tid,
        )
    except Exception as hlc_exc:
        _log.warning(
            "habitat_lifecycle candidate_preview registration failed (non-fatal): %s",
            type(hlc_exc).__name__,
        )
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.HABITAT_MATERIALIZATION_FAILED,
            {
                "materialization_kind": "candidate_preview",
                "thread_id": str(tid),
                "error": type(hlc_exc).__name__,
                "build_candidate_id": str(cand.build_candidate_id),
            },
            thread_id=tid,
        )

    return {
        "build_candidate": step_state["build_candidate"],
        "build_candidate_id": str(cand.build_candidate_id),
        "current_state": step_state["current_state"],
        "last_build_candidate_summary_v1": summary_v1,
        "last_build_candidate_summary_v2": summary_v2,
    }
