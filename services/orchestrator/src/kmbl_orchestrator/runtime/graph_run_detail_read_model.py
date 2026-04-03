"""Graph run detail read model — operator-facing view of a single graph run from persisted rows."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    BuildSpecRecord,
    CheckpointRecord,
    EvaluationReportRecord,
    GraphRunEventRecord,
    GraphRunRecord,
    PublicationSnapshotRecord,
    RoleInvocationRecord,
    StagingSnapshotRecord,
    ThreadRecord,
)
from kmbl_orchestrator.runtime.graph_run_attention import derive_graph_run_attention
from kmbl_orchestrator.runtime.operator_action_read_model import (
    build_operator_actions_from_events,
    is_operator_triggered_event,
    resume_stats_from_events,
)
from kmbl_orchestrator.runtime.run_events import RunEventType

# Subset of persisted role_invocation.routing_metadata_json (generator only) for operator UI.
# KiloClaw transport trace (all roles) — from role_invocation.routing_metadata_json
_TRANSPORT_TRACE_KEYS: tuple[str, ...] = (
    "kiloclaw_transport_configured",
    "kiloclaw_transport_resolved",
    "kiloclaw_stub_mode",
    "kiloclaw_api_key_present",
    "kiloclaw_auto_resolution_note",
    "kiloclaw_openclaw_cli_path",
)

_ROUTING_HINT_KEYS: tuple[str, ...] = (
    "kmb_routing_version",
    "generator_route_kind",
    "provider_config_key",
    "openai_image_route_applied",
    "budget_denial_reason",
    "image_generation_intent_kind",
    "route_reason",
    "image_generation_requested",
    "image_requested",
    "openai_image_route_requested",
    "estimated_tokens_reserved",
    "budget_cap_tokens",
    "budget_remaining_tokens",
)


def _routing_hints_payload(
    r: RoleInvocationRecord,
) -> tuple[dict[str, Any] | None, str]:
    """Return (hints dict or None, routing_fact_source: persisted | none)."""
    if r.role_type != "generator":
        return None, "none"
    rm = dict(r.routing_metadata_json or {})
    if not rm:
        return None, "none"
    hints = {k: rm[k] for k in _ROUTING_HINT_KEYS if k in rm}
    if not hints:
        return None, "none"
    return hints, "persisted"


def _quality_and_pressure_from_persisted(
    *,
    events: list[GraphRunEventRecord],
    invocations: list[RoleInvocationRecord],
    ev: EvaluationReportRecord | None,
) -> dict[str, Any]:
    """Durable quality / v1 pressure signals from persisted rows (not process memory)."""
    rescue_events = sum(
        1 for e in events if e.event_type == RunEventType.NORMALIZATION_RESCUE
    )
    inv_rescue = sum(
        1
        for r in invocations
        if r.role_type == "generator"
        and (r.routing_metadata_json or {}).get("normalization_rescue") is True
    )
    ws_updates = sum(1 for e in events if e.event_type == RunEventType.WORKING_STAGING_UPDATED)
    snap_created = sum(1 for e in events if e.event_type == RunEventType.STAGING_SNAPSHOT_CREATED)
    snap_skipped = sum(1 for e in events if e.event_type == RunEventType.STAGING_SNAPSHOT_SKIPPED)
    eval_status = ev.status if ev else None
    return {
        "durable_normalization_rescue": {
            "event_count": rescue_events,
            "generator_invocation_flag_count": inv_rescue,
        },
        "v1_pressure_telemetry": {
            "note": (
                "Lightweight governance signals from persisted graph_run_event rows and role_invocation "
                "metadata — extensible; not a full autonomy policy."
            ),
            "normalization_rescue_event_count": rescue_events,
            "working_staging_update_event_count": ws_updates,
            "staging_snapshot_created_event_count": snap_created,
            "staging_snapshot_skipped_event_count": snap_skipped,
            "latest_evaluation_status": eval_status,
            "evaluation_is_partial_or_fail": eval_status in ("partial", "fail"),
        },
    }


def _max_iteration(invocations: list[RoleInvocationRecord]) -> int | None:
    if not invocations:
        return None
    return max(r.iteration_index for r in invocations)


def _run_state_hint(status: str, *, has_interrupt_signal: bool) -> str:
    if status == "paused":
        return "paused"
    if status == "failed":
        return "failed"
    if status == "completed":
        return "completed"
    if status == "interrupted":
        return "interrupted (cooperative stop)"
    if status == "interrupt_requested":
        return "interrupt requested — stop pending at next graph boundary"
    if status == "starting":
        return "starting (queued / not yet executing)"
    if status == "running":
        if has_interrupt_signal:
            return "running (interrupt checkpoint present — may be paused awaiting resume)"
        return "running"
    return status


def _timeline_item_from_event(e: GraphRunEventRecord) -> dict[str, Any]:
    et = e.event_type
    payload = dict(e.payload_json or {})
    kind = "event"
    label = et
    related_id: str | None = None

    mapping: dict[str, tuple[str, str]] = {
        RunEventType.GRAPH_RUN_RESUMED: ("operator_resume", "Operator resumed execution"),
        RunEventType.GRAPH_RUN_STARTED: ("run_started", "Graph run started"),
        RunEventType.PLANNER_INVOCATION_STARTED: ("planner_started", "Planner invocation started"),
        RunEventType.PLANNER_INVOCATION_COMPLETED: ("planner_completed", "Planner invocation completed"),
        RunEventType.GENERATOR_INVOCATION_STARTED: ("generator_started", "Generator invocation started"),
        RunEventType.GENERATOR_INVOCATION_COMPLETED: ("generator_completed", "Generator invocation completed"),
        RunEventType.EVALUATOR_INVOCATION_STARTED: ("evaluator_started", "Evaluator invocation started"),
        RunEventType.EVALUATOR_INVOCATION_COMPLETED: ("evaluator_completed", "Evaluator invocation completed"),
        RunEventType.DECISION_MADE: ("decision", "Decision recorded"),
        RunEventType.GRAPH_RUN_COMPLETED: ("run_completed", "Graph run completed"),
        RunEventType.GRAPH_RUN_FAILED: ("run_failed", "Graph run failed"),
        RunEventType.INTERRUPT_REQUESTED: ("interrupt_requested", "Interrupt requested by operator"),
        RunEventType.INTERRUPT_ACKNOWLEDGED: ("interrupt_acknowledged", "Interrupt acknowledged at boundary"),
        RunEventType.GRAPH_RUN_INTERRUPTED: ("run_interrupted", "Graph run interrupted"),
        RunEventType.STAGING_SNAPSHOT_CREATED: ("staging_created", "Staging snapshot created"),
        RunEventType.STAGING_SNAPSHOT_SKIPPED: (
            "staging_skipped",
            "Review snapshot skipped (policy or nomination)",
        ),
        RunEventType.WORKING_STAGING_UPDATED: (
            "working_staging_updated",
            "Working staging updated (live)",
        ),
        RunEventType.STAGING_SNAPSHOT_BLOCKED: ("staging_blocked", "Staging snapshot blocked"),
        RunEventType.STAGING_SNAPSHOT_APPROVED: ("staging_approved", "Staging snapshot approved (audit)"),
        RunEventType.STAGING_SNAPSHOT_UNAPPROVED: (
            "staging_unapproved",
            "Staging approval withdrawn (operator)",
        ),
        RunEventType.STAGING_SNAPSHOT_REJECTED: ("staging_rejected", "Staging snapshot rejected (operator)"),
        RunEventType.PUBLICATION_SNAPSHOT_CREATED: ("publication_created", "Publication snapshot created"),
        RunEventType.CROSS_RUN_MEMORY_LOADED: (
            "cross_run_memory_loaded",
            "Cross-run memory loaded for planner",
        ),
        RunEventType.CROSS_RUN_MEMORY_UPDATED: (
            "cross_run_memory_updated",
            "Cross-run memory updated",
        ),
    }
    if et in mapping:
        kind, label = mapping[et]

    operator_triggered = is_operator_triggered_event(et)

    if et in (
        RunEventType.STAGING_SNAPSHOT_CREATED,
        RunEventType.STAGING_SNAPSHOT_APPROVED,
        RunEventType.STAGING_SNAPSHOT_UNAPPROVED,
        RunEventType.STAGING_SNAPSHOT_REJECTED,
    ):
        sid = payload.get("staging_snapshot_id")
        if isinstance(sid, str):
            related_id = sid
    elif et == RunEventType.PUBLICATION_SNAPSHOT_CREATED:
        pid = payload.get("publication_snapshot_id")
        if isinstance(pid, str):
            related_id = pid

    return {
        "kind": kind,
        "label": label,
        "timestamp": e.created_at,
        "related_id": related_id,
        "event_type": et,
        "operator_triggered": operator_triggered,
    }


def build_graph_run_detail_read_model(
    *,
    thread: ThreadRecord | None,
    gr: GraphRunRecord,
    invocations: list[RoleInvocationRecord],
    staging_rows: list[StagingSnapshotRecord],
    publications: list[PublicationSnapshotRecord],
    events: list[GraphRunEventRecord],
    latest_checkpoint: CheckpointRecord | None,
    has_interrupt_signal: bool,
    bs: BuildSpecRecord | None,
    bc: BuildCandidateRecord | None,
    ev: EvaluationReportRecord | None,
) -> dict[str, Any]:
    """Assemble structured dict for GraphRunDetailResponse (no raw role payloads)."""
    inv_sorted = sorted(invocations, key=lambda r: r.started_at)
    inv_out = []
    for r in inv_sorted:
        rh, rsrc = _routing_hints_payload(r)
        rm = dict(r.routing_metadata_json or {})
        tt = {k: rm[k] for k in _TRANSPORT_TRACE_KEYS if k in rm}
        row: dict[str, Any] = {
            "role_invocation_id": str(r.role_invocation_id),
            "role_type": r.role_type,
            "status": r.status,
            "iteration_index": r.iteration_index,
            "started_at": r.started_at,
            "ended_at": r.ended_at,
            "provider": r.provider,
            "provider_config_key": r.provider_config_key,
            "routing_fact_source": rsrc,
        }
        if tt:
            row["kiloclaw_transport_trace"] = tt
        if r.role_type == "generator" and rm.get("normalization_rescue"):
            row["normalization_rescue"] = True
        if rh is not None:
            row["routing_hints"] = rh
        inv_out.append(row)

    events_sorted = sorted(events, key=lambda e: e.created_at)
    timeline = [_timeline_item_from_event(e) for e in events_sorted]

    resume_count, last_resumed_at = resume_stats_from_events(events)
    operator_actions = build_operator_actions_from_events(events)

    staging_id = str(staging_rows[0].staging_snapshot_id) if staging_rows else None
    pub_id = str(publications[0].publication_snapshot_id) if publications else None

    eff_id = gr.identity_id or (thread.identity_id if thread else None)
    identity_s = str(eff_id) if eff_id else None
    graph_run_identity_s = str(gr.identity_id) if gr.identity_id else None

    snapshot_skipped_intentionally = any(
        e.event_type == RunEventType.STAGING_SNAPSHOT_SKIPPED for e in events_sorted
    )

    hint = _run_state_hint(gr.status, has_interrupt_signal=has_interrupt_signal)
    att_state, att_reason = derive_graph_run_attention(
        status=gr.status,
        has_interrupt_signal=has_interrupt_signal,
        latest_staging_snapshot_id=staging_id,
        snapshot_skipped_intentionally=snapshot_skipped_intentionally,
    )

    first_planner = next((r for r in inv_sorted if r.role_type == "planner"), None)
    planner_tt: dict[str, Any] | None = None
    if first_planner:
        prm = dict(first_planner.routing_metadata_json or {})
        planner_tt = {k: prm[k] for k in _TRANSPORT_TRACE_KEYS if k in prm}

    summary_extra: dict[str, Any] = {}
    if planner_tt:
        summary_extra["kiloclaw_transport_trace"] = planner_tt

    qp = _quality_and_pressure_from_persisted(
        events=events_sorted,
        invocations=inv_sorted,
        ev=ev,
    )

    return {
        "summary": {
            "graph_run_id": str(gr.graph_run_id),
            "thread_id": str(gr.thread_id),
            "identity_id": identity_s,
            "graph_run_identity_id": graph_run_identity_s,
            "trigger_type": gr.trigger_type,
            "status": gr.status,
            "interrupt_requested_at": gr.interrupt_requested_at,
            "started_at": gr.started_at,
            "ended_at": gr.ended_at,
            "max_iteration_index": _max_iteration(invocations),
            "latest_checkpoint_id": str(latest_checkpoint.checkpoint_id) if latest_checkpoint else None,
            "run_state_hint": hint,
            "attention_state": att_state,
            "attention_reason": att_reason,
            "resume_count": resume_count,
            "last_resumed_at": last_resumed_at,
            **summary_extra,
            "quality_metrics": qp["durable_normalization_rescue"],
            "pressure_summary": qp["v1_pressure_telemetry"],
        },
        "operator_actions": operator_actions,
        "role_invocations": inv_out,
        "associated_outputs": {
            "build_spec_id": str(bs.build_spec_id) if bs else None,
            "build_candidate_id": str(bc.build_candidate_id) if bc else None,
            "evaluation_report_id": str(ev.evaluation_report_id) if ev else None,
            "staging_snapshot_id": staging_id,
            "publication_snapshot_id": pub_id,
            "alignment_score": ev.alignment_score if ev else None,
            "alignment_signals_json": dict(ev.alignment_signals_json or {})
            if ev
            else {},
        },
        "timeline": timeline,
    }
