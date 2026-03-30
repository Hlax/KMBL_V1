"""Reconcile graph_run rows stuck in ``running`` beyond a time threshold."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.contracts.normalized_errors import STALE_RUN_MESSAGE
from kmbl_orchestrator.domain import CheckpointRecord, GraphRunRecord
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event


def _started_at_utc(gr: GraphRunRecord) -> datetime | None:
    try:
        return datetime.fromisoformat(gr.started_at.replace("Z", "+00:00"))
    except ValueError:
        return None


def graph_run_is_stale_running(gr: GraphRunRecord, threshold_seconds: int) -> bool:
    if threshold_seconds <= 0 or gr.status != "running":
        return False
    started = _started_at_utc(gr)
    if started is None:
        return False
    return datetime.now(timezone.utc) - started > timedelta(seconds=threshold_seconds)


def reconcile_stale_running_graph_run(
    repo: Repository,
    settings: Settings,
    graph_run_id: UUID,
) -> bool:
    """
    If this graph_run is still ``running`` and older than the stale threshold, mark ``failed``.

    Writes interrupt checkpoint + timeline event. Returns True if a change was applied.
    """
    gr = repo.get_graph_run(graph_run_id)
    if gr is None:
        return False
    th = settings.orchestrator_running_stale_after_seconds
    if not graph_run_is_stale_running(gr, th):
        return False
    ended = datetime.now(timezone.utc).isoformat()
    repo.update_graph_run_status(graph_run_id, "failed", ended)
    repo.save_checkpoint(
        CheckpointRecord(
            checkpoint_id=uuid4(),
            thread_id=gr.thread_id,
            graph_run_id=graph_run_id,
            checkpoint_kind="interrupt",
            state_json={
                "orchestrator_error": {
                    "error_kind": "orchestrator_stale_run",
                    "error_message": STALE_RUN_MESSAGE,
                }
            },
            context_compaction_json=None,
        )
    )
    append_graph_run_event(
        repo,
        graph_run_id,
        RunEventType.GRAPH_RUN_FAILED,
        {
            "reason": "orchestrator_stale_run",
            "threshold_seconds": th,
        },
    )
    return True


def reconcile_all_stale_running_graph_runs(repo: Repository, settings: Settings) -> int:
    """Batch helper (tests / manual ops)."""
    ids = repo.list_stale_running_graph_run_ids(
        settings.orchestrator_running_stale_after_seconds
    )
    n = 0
    for gid in ids:
        if reconcile_stale_running_graph_run(repo, settings, gid):
            n += 1
    return n
