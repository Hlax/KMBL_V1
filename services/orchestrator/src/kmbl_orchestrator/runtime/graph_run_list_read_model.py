"""Graph run list read model — compact index view of graph run rows for the operator dashboard."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.domain import GraphRunRecord
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.runtime.graph_run_attention import derive_graph_run_attention
from kmbl_orchestrator.runtime.graph_run_detail_read_model import _run_state_hint
from kmbl_orchestrator.runtime.scenario_visibility import (
    scenario_badge_from_tag,
    scenario_tag_from_run_state,
)


def build_graph_run_list_read_model(
    repo: Repository,
    runs: list[GraphRunRecord],
) -> list[dict[str, Any]]:
    """Return dicts for GraphRunListItem — no snapshot payloads."""
    if not runs:
        return []
    gids = [r.graph_run_id for r in runs]
    stats = repo.aggregate_role_invocation_stats_for_graph_runs(gids)
    staging = repo.latest_staging_snapshot_ids_for_graph_runs(gids)
    interrupts = repo.graph_run_ids_with_interrupt_orchestrator_error(gids)
    thread_ids = list({r.thread_id for r in runs})
    threads = {tid: repo.get_thread(tid) for tid in thread_ids}
    out: list[dict[str, Any]] = []
    for gr in runs:
        count, max_iter = stats.get(gr.graph_run_id, (0, None))
        th = threads.get(gr.thread_id)
        if gr.identity_id:
            identity = str(gr.identity_id)
        elif th and th.identity_id:
            identity = str(th.identity_id)
        else:
            identity = None
        sid = staging.get(gr.graph_run_id)
        has_intr = gr.graph_run_id in interrupts
        hint = _run_state_hint(gr.status, has_interrupt_signal=has_intr)
        staging_s = str(sid) if sid else None
        att_state, att_reason = derive_graph_run_attention(
            status=gr.status,
            has_interrupt_signal=has_intr,
            latest_staging_snapshot_id=staging_s,
        )
        snap = repo.get_run_snapshot(gr.graph_run_id)
        scen_tag = scenario_tag_from_run_state(snap)
        scen_badge = scenario_badge_from_tag(scen_tag)
        out.append(
            {
                "graph_run_id": str(gr.graph_run_id),
                "thread_id": str(gr.thread_id),
                "identity_id": identity,
                "trigger_type": gr.trigger_type,
                "status": gr.status,
                "started_at": gr.started_at,
                "ended_at": gr.ended_at,
                "max_iteration_index": max_iter,
                "run_state_hint": hint,
                "role_invocation_count": count,
                "latest_staging_snapshot_id": staging_s,
                "attention_state": att_state,
                "attention_reason": att_reason,
                "scenario_tag": scen_tag,
                "scenario_badge": scen_badge,
            }
        )
    return out
