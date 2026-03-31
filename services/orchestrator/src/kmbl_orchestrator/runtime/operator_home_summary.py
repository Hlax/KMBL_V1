"""Operator home summary — compact dashboard read model from persisted rows."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.runtime.graph_run_list_read_model import build_graph_run_list_read_model
from kmbl_orchestrator.staging.review_action import derive_review_action_state

_RUN_WINDOW = 200
_STAGING_WINDOW = 500


def build_operator_home_summary(repo: Repository) -> dict[str, Any]:
    """
    Aggregate recent persisted graph runs and staging snapshots + latest publication.

    Windows are bounded — not a full-table analytics pass.
    """
    runs = repo.list_graph_runs(
        status=None,
        trigger_type=None,
        identity_id=None,
        limit=_RUN_WINDOW,
    )
    run_rows = build_graph_run_list_read_model(repo, runs)
    runs_needing_attention = sum(
        1 for r in run_rows if r.get("attention_state") != "healthy"
    )
    failed_count = sum(1 for r in run_rows if r.get("status") == "failed")
    paused_count = sum(1 for r in run_rows if r.get("status") == "paused")

    staging_rows = repo.list_staging_snapshots(
        limit=_STAGING_WINDOW,
        status=None,
        identity_id=None,
    )
    sids = [r.staging_snapshot_id for r in staging_rows]
    pub_counts = repo.publication_counts_for_staging_snapshot_ids(sids)
    rq = {
        "ready_for_review": 0,
        "ready_to_publish": 0,
        "published": 0,
        "not_actionable": 0,
    }
    for rec in staging_rows:
        pc = pub_counts.get(rec.staging_snapshot_id, 0)
        action, _ = derive_review_action_state(rec, pc)
        if action in rq:
            rq[action] += 1

    latest = repo.get_latest_publication_snapshot(identity_id=None)
    canon = {
        "has_current_publication": latest is not None,
        "latest_publication_snapshot_id": str(latest.publication_snapshot_id)
        if latest
        else None,
        "latest_published_at": latest.published_at if latest else None,
    }

    return {
        "basis": "persisted_rows_only",
        "runtime": {
            "runs_in_window": len(run_rows),
            "runs_needing_attention": runs_needing_attention,
            "failed_count": failed_count,
            "paused_count": paused_count,
        },
        "review_queue": rq,
        "canon": canon,
    }
