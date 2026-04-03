"""evaluator_node — invoke the evaluator role and persist the evaluation report."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from kmbl_orchestrator.contracts.normalized_errors import contract_validation_failure
from kmbl_orchestrator.contracts.evaluator_nomination import extract_evaluator_nomination
from kmbl_orchestrator.contracts.persistence_validate import (
    validate_role_output_for_persistence,
)
from kmbl_orchestrator.domain import CheckpointRecord
from kmbl_orchestrator.errors import KiloclawRoleInvocationForbiddenError, RoleInvocationFailed
from kmbl_orchestrator.graph.helpers import (
    _persist_invocation_failure,
    _save_checkpoint_with_event,
)
from kmbl_orchestrator.graph.state import GraphState
from kmbl_orchestrator.identity.alignment import score_alignment
from kmbl_orchestrator.normalize import normalize_evaluator_output
from kmbl_orchestrator.normalize.gallery_strip_harness import (
    merge_gallery_strip_harness_checks,
)
from kmbl_orchestrator.runtime.evaluation_surface_gate import apply_preview_surface_gate
from kmbl_orchestrator.runtime.interrupt_checks import raise_if_interrupt_requested
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event
from kmbl_orchestrator.runtime.session_staging_links import resolve_evaluator_preview_url
from kmbl_orchestrator.staging.duplicate_rejection import apply_duplicate_staging_rejection
from kmbl_orchestrator.staging.facts import (
    build_working_staging_facts,
    working_staging_facts_to_payload,
)

if TYPE_CHECKING:
    from kmbl_orchestrator.graph.app import GraphContext

_log = logging.getLogger(__name__)


def evaluator_node(ctx: "GraphContext", state: GraphState) -> dict[str, Any]:
    """Invoke the evaluator role and persist the evaluation report."""
    gid = UUID(state["graph_run_id"])
    tid = UUID(state["thread_id"])
    raise_if_interrupt_requested(ctx.repo, gid, tid)
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
    _save_checkpoint_with_event(ctx.repo, cp0)
    append_graph_run_event(ctx.repo, gid, RunEventType.EVALUATOR_INVOCATION_STARTED, {}, thread_id=tid)
    _log.info(
        "graph_run graph_run_id=%s stage=evaluator_invocation_start elapsed_ms=0.0",
        gid,
    )

    spec = ctx.repo.get_build_spec(UUID(bsid))
    if spec is None:
        raise RoleInvocationFailed(
            phase="evaluator",
            graph_run_id=gid,
            thread_id=tid,
            detail={
                "error_kind": "configuration_error",
                "message": f"build_spec not found for build_spec_id={bsid}",
            },
        )
    success = spec.success_criteria_json
    targets = spec.evaluation_targets_json

    ws = ctx.repo.get_working_staging_for_thread(tid)
    ws_facts: dict[str, Any] | None = None
    user_rating_context: dict[str, Any] | None = None
    if ws is not None:
        checkpoints = ctx.repo.list_staging_checkpoints(ws.working_staging_id, limit=5)
        latest_cp = checkpoints[0] if checkpoints else None
        facts = build_working_staging_facts(
            ws,
            checkpoint_count=len(checkpoints),
            latest_checkpoint_revision=latest_cp.revision_at_checkpoint if latest_cp else None,
            latest_checkpoint_trigger=latest_cp.trigger if latest_cp else None,
            patches_since_rebuild=(ws.revision - (ws.last_rebuild_revision or 0)),
            stagnation_count=ws.stagnation_count,
        )
        ws_facts = working_staging_facts_to_payload(facts)
    
    # Get user rating context for evaluator
    staging_snapshots = ctx.repo.list_staging_snapshots_for_thread(tid, limit=5)
    for snap in staging_snapshots:
        if snap.user_rating is not None:
            user_rating_context = {
                "rating": snap.user_rating,
                "feedback": snap.user_feedback,
                "rated_at": snap.rated_at,
                "from_staging_id": str(snap.staging_snapshot_id),
            }
            break

    bc = state.get("build_candidate") if isinstance(state.get("build_candidate"), dict) else {}
    iter_hint = int(state.get("iteration_index", 0))
    prev_ev = state.get("evaluation_report") if iter_hint > 0 else None
    preview_url = resolve_evaluator_preview_url(
        ctx.settings,
        graph_run_id=str(gid),
        thread_id=str(tid),
        build_candidate=bc,
    )
    payload = {
        "thread_id": state["thread_id"],
        "build_candidate": bc,
        "success_criteria": success,
        "evaluation_targets": targets,
        "iteration_hint": iter_hint,
        "working_staging_facts": ws_facts,
        "user_rating_context": user_rating_context,
        # Fix 1+2: identity_brief enables evaluator to produce alignment_report
        "identity_brief": state.get("identity_brief"),
        # Structured identity profile: themes, tone, visual_tendencies, content_types,
        # complexity — enables intent-aware judgment (experience_mode alignment, spatial checks).
        "structured_identity": state.get("structured_identity"),
        # Prefer live assembled staging preview for Playwright / visual grounding
        "preview_url": preview_url,
        "iteration_context": {
            "iteration_index": iter_hint,
            "has_previous_evaluation_report": bool(prev_ev),
        },
        # Prior evaluator JSON (same thread run) for visual-delta / sameness checks
        "previous_evaluation_report": prev_ev if iter_hint > 0 else None,
    }
    t_ev = time.perf_counter()
    try:
        inv, raw = ctx.invoker.invoke(
            graph_run_id=gid,
            thread_id=tid,
            role_type="evaluator",
            provider_config_key=ctx.settings.kiloclaw_evaluator_config_key,
            input_payload=payload,
            iteration_index=int(state.get("iteration_index", 0)),
        )
    except KiloclawRoleInvocationForbiddenError as e:
        raise RoleInvocationFailed(
            phase="evaluator",
            graph_run_id=gid,
            thread_id=tid,
            detail={
                "error_kind": "transport_forbidden",
                "message": str(e),
                "operator_hint": e.operator_hint,
            },
        ) from e
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
    ev_input = state.get("event_input") or {}
    is_static_vertical = (
        ev_input.get("scenario", "").startswith("kmbl_identity_url_static")
        or (ev_input.get("constraints") or {}).get("canonical_vertical") == "static_frontend_file_v1"
    )
    if bc_row is not None and not is_static_vertical:
        report = merge_gallery_strip_harness_checks(report, bc_row)
    if bc_row is not None:
        prev_ev_status = report.status
        report = apply_duplicate_staging_rejection(
            report,
            bc=bc_row,
            repo=ctx.repo,
            thread_id=tid,
            graph_run_id=gid,
        )
        if (
            prev_ev_status != report.status
            and report.metrics_json.get("duplicate_rejection")
        ):
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.CONTRACT_WARNING,
                {
                    "kind": "duplicate_static_output",
                    "previous_status": prev_ev_status,
                    "duplicate_of_staging_snapshot_id": report.metrics_json.get(
                        "duplicate_of_staging_snapshot_id"
                    ),
                },
                thread_id=tid,
            )
    report = apply_preview_surface_gate(report, is_static_vertical=is_static_vertical)

    # ── 3D content guardrail for spatial experience modes ────────────────
    # Soft policy: do not force fail when the LLM evaluator already passed — use partial + metrics
    # so the graph can iterate without a hard dead-end before the generator adds Three/WebGL.
    bs_from_state = state.get("build_spec") or {}
    exp_mode = bs_from_state.get("experience_mode", "")
    if exp_mode in ("immersive_spatial_portfolio", "webgl_3d_portfolio"):
        _3d_keywords = {"three", "webgl", "3d"}
        has_3d_content = False
        candidate_artifacts = bc.get("artifact_outputs") or []
        for art in candidate_artifacts:
            art_role = str(art.get("role", "")).lower()
            art_content = str(art.get("content", "")).lower()
            art_path = str(art.get("path", "")).lower()
            searchable = f"{art_role} {art_content} {art_path}"
            if any(kw in searchable for kw in _3d_keywords):
                has_3d_content = True
                break
        if not has_3d_content and report.status in ("pass", "partial"):
            _log.warning(
                "graph_run graph_run_id=%s 3d_content_guardrail: "
                "experience_mode=%s but no 3D content found in artifacts; "
                "recording partial + metrics (not hard fail)",
                gid,
                exp_mode,
            )
            existing_issues = list(report.issues_json or [])
            existing_issues.append({
                "severity": "high",
                "category": "3d_content_missing",
                "message": (
                    f"experience_mode is '{exp_mode}' but build candidate "
                    "contains no WebGL/Three.js/3D content — iterate to add real 3D or lower ambition in build_spec"
                ),
            })
            m = dict(report.metrics_json or {})
            m["experience_mode_3d_unfulfilled"] = True
            m["experience_mode_requested"] = exp_mode
            new_status = "partial"
            report = report.model_copy(
                update={
                    "status": new_status,
                    "issues_json": existing_issues,
                    "metrics_json": m,
                }
            )

    # Fix 2: compute alignment score from evaluator output + identity_brief
    identity_brief = state.get("identity_brief")
    alignment_score: float | None = None
    alignment_signals: dict[str, Any] = {}
    if identity_brief:
        cand_artifact_refs: list[Any] = []
        if bc_row is not None:
            cand_artifact_refs = list(bc_row.artifact_refs_json or [])
        alignment_score, alignment_signals = score_alignment(
            metrics=report.metrics_json,
            artifact_refs=cand_artifact_refs,
            identity_brief=identity_brief,
        )
        if alignment_score is not None:
            _log.info(
                "graph_run graph_run_id=%s alignment_score=%.3f source=%s",
                gid,
                alignment_score,
                alignment_signals.get("source", "unknown"),
            )

    report = report.model_copy(update={
        "raw_payload_json": raw,
        "alignment_score": alignment_score,
        "alignment_signals_json": alignment_signals,
    })

    evaluator_nomination = extract_evaluator_nomination(
        raw if isinstance(raw, dict) else None
    )

    # Update alignment score history in state
    alignment_history: list[dict[str, Any]] = list(
        state.get("alignment_score_history") or []
    )
    if alignment_score is not None:
        alignment_history.append({
            "iteration_index": int(state.get("iteration_index", 0)),
            "score": alignment_score,
        })

    step_state = {
        **dict(state),
        "evaluation_report": {
            "status": report.status,
            "summary": report.summary,
            "issues": report.issues_json,
            "metrics": report.metrics_json,
            "artifacts": report.artifacts_json,
            # Include alignment so decision_router can use it
            "alignment_score": alignment_score,
            "alignment_signals": alignment_signals,
        },
        "evaluation_report_id": str(report.evaluation_report_id),
        "alignment_score_history": alignment_history,
        "last_alignment_score": alignment_score,
    }
    with ctx.repo.transaction():
        ctx.repo.save_evaluation_report(report)
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
            RunEventType.EVALUATOR_INVOCATION_COMPLETED,
            {"evaluation_report_id": str(report.evaluation_report_id)},
        )
    return {
        "evaluation_report": step_state["evaluation_report"],
        "evaluation_report_id": str(report.evaluation_report_id),
        "alignment_score_history": step_state["alignment_score_history"],
        "last_alignment_score": step_state["last_alignment_score"],
        "evaluator_nomination": evaluator_nomination,
    }
