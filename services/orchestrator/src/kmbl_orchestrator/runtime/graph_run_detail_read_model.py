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
        RunEventType.STAGING_SNAPSHOT_CREATED: ("staging_created", "Staging snapshot created"),
        RunEventType.STAGING_SNAPSHOT_BLOCKED: ("staging_blocked", "Staging snapshot blocked"),
        RunEventType.STAGING_SNAPSHOT_APPROVED: ("staging_approved", "Staging snapshot approved (audit)"),
        RunEventType.STAGING_SNAPSHOT_UNAPPROVED: (
            "staging_unapproved",
            "Staging approval withdrawn (operator)",
        ),
        RunEventType.STAGING_SNAPSHOT_REJECTED: ("staging_rejected", "Staging snapshot rejected (operator)"),
        RunEventType.PUBLICATION_SNAPSHOT_CREATED: ("publication_created", "Publication snapshot created"),
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

    hint = _run_state_hint(gr.status, has_interrupt_signal=has_interrupt_signal)
    att_state, att_reason = derive_graph_run_attention(
        status=gr.status,
        has_interrupt_signal=has_interrupt_signal,
        latest_staging_snapshot_id=staging_id,
    )

    return {
        "summary": {
            "graph_run_id": str(gr.graph_run_id),
            "thread_id": str(gr.thread_id),
            "identity_id": identity_s,
            "graph_run_identity_id": graph_run_identity_s,
            "trigger_type": gr.trigger_type,
            "status": gr.status,
            "started_at": gr.started_at,
            "ended_at": gr.ended_at,
            "max_iteration_index": _max_iteration(invocations),
            "latest_checkpoint_id": str(latest_checkpoint.checkpoint_id) if latest_checkpoint else None,
            "run_state_hint": hint,
            "attention_state": att_state,
            "attention_reason": att_reason,
            "resume_count": resume_count,
            "last_resumed_at": last_resumed_at,
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
