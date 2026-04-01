"""staging_node — apply the build candidate to working staging and create a snapshot."""

from __future__ import annotations

import copy
import logging
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from kmbl_orchestrator.contracts.evaluator_nomination import extract_evaluator_nomination
from kmbl_orchestrator.domain import (
    StagingSnapshotRecord,
    WorkingStagingRecord,
)
from kmbl_orchestrator.errors import StagingIntegrityFailed
from kmbl_orchestrator.graph.state import GraphState
from kmbl_orchestrator.identity.hydrate import upsert_identity_evolution_signal
from kmbl_orchestrator.runtime.interrupt_checks import raise_if_interrupt_requested
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event
from kmbl_orchestrator.staging.build_snapshot import build_staging_snapshot_payload
from kmbl_orchestrator.staging.integrity import validate_preview_integrity
from kmbl_orchestrator.staging.pressure import pressure_evaluation_to_event_payload
from kmbl_orchestrator.staging.working_staging_ops import (
    apply_generator_to_working_staging,
    choose_update_mode_with_pressure,
    create_pre_rebuild_checkpoint,
    create_staging_checkpoint,
    should_auto_checkpoint_with_policy,
)

if TYPE_CHECKING:
    from kmbl_orchestrator.graph.app import GraphContext

_log = logging.getLogger(__name__)


def _should_create_staging_snapshot(policy: str, marked_for_review: bool) -> bool:
    if policy == "always":
        return True
    if policy == "never":
        return False
    if policy == "on_nomination":
        return marked_for_review
    return True


def staging_node(ctx: "GraphContext", state: GraphState) -> dict[str, Any]:
    """Apply the build candidate to working staging and create a snapshot."""
    gid = UUID(state["graph_run_id"])
    tid = UUID(state["thread_id"])
    raise_if_interrupt_requested(ctx.repo, gid, tid)
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
    if ev.status not in ("pass", "partial", "fail"):
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
            message="evaluation_report.status must be pass, partial, or fail to stage (blocked is not stageable)",
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
    t_st = time.perf_counter()

    # --- Working staging path (primary) ---
    ws = ctx.repo.get_working_staging_for_thread(tid)

    mode, pressure_eval, mode_reason = choose_update_mode_with_pressure(
        ws, ev.status, evaluation_issue_count=len(ev.issues_json)
    )

    if ws is None:
        ws = WorkingStagingRecord(
            working_staging_id=uuid4(),
            thread_id=tid,
            identity_id=thread.identity_id,
        )

    before_snapshot = copy.deepcopy(ws)

    pressure_score = pressure_eval.pressure_score if pressure_eval else 0.0
    if mode == "rebuild" and ws.revision > 0:
        pre_cp = create_pre_rebuild_checkpoint(
            ws, source_graph_run_id=gid, pressure_score=pressure_score,
        )
        if pre_cp:
            ctx.repo.save_staging_checkpoint(pre_cp)
            ws.current_checkpoint_id = pre_cp.staging_checkpoint_id
            append_graph_run_event(
                ctx.repo, gid,
                RunEventType.WORKING_STAGING_CHECKPOINT_CREATED,
                {
                    "staging_checkpoint_id": str(pre_cp.staging_checkpoint_id),
                    "trigger": pre_cp.trigger,
                    "reason_category": pre_cp.reason_category,
                },
            )

    ws = apply_generator_to_working_staging(
        working_staging=ws,
        build_candidate=bc,
        evaluation_report=ev,
        build_spec=spec,
        mode=mode,
        mode_reason_category=mode_reason,
        pressure_evaluation=pressure_eval,
    )

    trigger, reason = should_auto_checkpoint_with_policy(
        before_snapshot, ws, mode, pressure_score=pressure_score,
    )
    if trigger:
        post_cp = create_staging_checkpoint(
            ws, trigger=trigger, source_graph_run_id=gid, reason=reason,
        )
        ctx.repo.save_staging_checkpoint(post_cp)
        ws.current_checkpoint_id = post_cp.staging_checkpoint_id
        append_graph_run_event(
            ctx.repo, gid,
            RunEventType.WORKING_STAGING_CHECKPOINT_CREATED,
            {
                "staging_checkpoint_id": str(post_cp.staging_checkpoint_id),
                "trigger": trigger,
                "reason_category": reason.category if reason else None,
            },
        )

    # Persist alignment score on working staging for trend detection
    alignment_score_for_ws: float | None = state.get("last_alignment_score")
    if alignment_score_for_ws is not None:
        ws.last_alignment_score = alignment_score_for_ws

    ctx.repo.save_working_staging(ws)

    event_payload: dict[str, Any] = {
        "working_staging_id": str(ws.working_staging_id),
        "mode": mode,
        "mode_reason": mode_reason,
        "revision": ws.revision,
        "status": ws.status,
        "thread_id": str(tid),
        "build_candidate_id": str(bc.build_candidate_id),
        "stagnation_count": ws.stagnation_count,
    }
    if pressure_eval:
        event_payload["pressure"] = pressure_evaluation_to_event_payload(pressure_eval)
    if ws.last_revision_summary_json:
        event_payload["revision_summary"] = ws.last_revision_summary_json

    append_graph_run_event(
        ctx.repo, gid,
        RunEventType.WORKING_STAGING_UPDATED,
        event_payload,
    )

    # --- Review snapshot row (immutable staging_snapshot) ---
    prior_on_thread = ctx.repo.list_staging_snapshots_for_thread(tid, limit=1)
    prior_staging_id: UUID | None = (
        prior_on_thread[0].staging_snapshot_id if prior_on_thread else None
    )

    nom_state = state.get("evaluator_nomination")
    raw_ev = ev.raw_payload_json if isinstance(ev.raw_payload_json, dict) else None
    # Always normalize via extract — same rules for checkpoint state dicts and raw evaluator JSON
    # (avoids unsafe bool() on ad-hoc dict values).
    nom_src = nom_state if isinstance(nom_state, dict) and nom_state else raw_ev
    nomination = extract_evaluator_nomination(nom_src if isinstance(nom_src, dict) else None)

    marked = nomination["marked_for_review"]
    mark_reason = nomination["mark_reason"]
    review_tags: list[str] = list(nomination["review_tags"])

    policy = getattr(ctx.settings, "staging_snapshot_policy", "always")
    should_snapshot = _should_create_staging_snapshot(policy, marked)

    ssid: UUID | None = None
    if should_snapshot:
        payload = build_staging_snapshot_payload(
            build_candidate=bc,
            evaluation_report=ev,
            thread=thread,
            build_spec=spec,
            prior_staging_snapshot_id=prior_staging_id,
        )
        ssid = uuid4()
        snap = StagingSnapshotRecord(
            staging_snapshot_id=ssid,
            thread_id=bc.thread_id,
            build_candidate_id=bc.build_candidate_id,
            graph_run_id=bc.graph_run_id,
            identity_id=thread.identity_id,
            prior_staging_snapshot_id=prior_staging_id,
            snapshot_payload_json=payload,
            preview_url=bc.preview_url,
            status="review_ready",
            marked_for_review=marked,
            mark_reason=mark_reason,
            review_tags=review_tags,
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
                "prior_staging_snapshot_id": str(prior_staging_id)
                if prior_staging_id is not None
                else None,
                "marked_for_review": marked,
                "staging_snapshot_policy": policy,
            },
        )
    else:
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.STAGING_SNAPSHOT_SKIPPED,
            {
                "thread_id": str(tid),
                "build_candidate_id": str(bc.build_candidate_id),
                "marked_for_review": marked,
                "staging_snapshot_policy": policy,
            },
            thread_id=tid,
        )

    # --- Evaluator → identity feedback loop ---
    # Upsert evaluation signals back into identity_profile so future planner
    # invocations on the same identity receive richer context about what has
    # and hasn't worked across runs.
    if thread.identity_id is not None:
        try:
            upsert_identity_evolution_signal(
                ctx.repo,
                thread.identity_id,
                graph_run_id=gid,
                evaluation_status=ev.status,
                evaluation_summary=ev.summary or "",
                issue_count=len(ev.issues_json),
                staging_snapshot_id=ssid,
                # Fix 2: alignment score is now part of the evolution signal
                alignment_score=ev.alignment_score,
            )
            fb_payload: dict[str, Any] = {
                "identity_id": str(thread.identity_id),
                "evaluation_status": ev.status,
                "issue_count": len(ev.issues_json),
            }
            if ssid is not None:
                fb_payload["staging_snapshot_id"] = str(ssid)
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.IDENTITY_FEEDBACK_UPSERT,
                fb_payload,
                thread_id=tid,
            )
        except Exception as fb_exc:
            _log.warning(
                "identity_feedback_upsert failed (non-fatal) identity_id=%s exc=%s",
                thread.identity_id,
                type(fb_exc).__name__,
            )

    _log.info(
        "graph_run graph_run_id=%s stage=staging_done working_staging_id=%s mode=%s revision=%d snapshot_id=%s elapsed_ms=%.1f",
        gid, ws.working_staging_id, mode, ws.revision, ssid,
        (time.perf_counter() - t_st) * 1000,
    )
    return {
        "staging_snapshot_id": str(ssid) if ssid is not None else None,
        "working_staging_id": str(ws.working_staging_id),
        "status": "completed",
    }
