"""Create a review snapshot row from current live working staging + persisted provenance rows."""

from __future__ import annotations

from uuid import UUID, uuid4

from kmbl_orchestrator.domain import StagingSnapshotRecord
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.staging.build_snapshot import build_staging_snapshot_payload


def materialize_review_snapshot_from_live(
    repo: Repository,
    thread_id: UUID,
) -> StagingSnapshotRecord:
    """
    Build a ``staging_snapshot`` from the latest build_candidate / evaluation_report
    on the working staging's last graph run, same shape as ``staging_node``.

    Use when ``staging_snapshot_policy`` skipped automatic snapshots but operators
    need a frozen review row (or to recover provenance for publication FK).
    """
    ws = repo.get_working_staging_for_thread(thread_id)
    if ws is None:
        raise ValueError("no_working_staging")
    if ws.revision == 0:
        raise ValueError("empty_working_staging")
    if ws.last_update_build_candidate_id is None or ws.last_update_graph_run_id is None:
        raise ValueError("missing_provenance")

    bc = repo.get_build_candidate(ws.last_update_build_candidate_id)
    if bc is None:
        raise ValueError("build_candidate_not_found")

    ev = repo.get_latest_evaluation_report_for_graph_run(ws.last_update_graph_run_id)
    if ev is None:
        raise ValueError("evaluation_report_not_found")

    thread = repo.get_thread(thread_id)
    if thread is None:
        raise ValueError("thread_not_found")

    spec = repo.get_build_spec(bc.build_spec_id)
    prior_on_thread = repo.list_staging_snapshots_for_thread(thread_id, limit=1)
    prior_staging_id: UUID | None = (
        prior_on_thread[0].staging_snapshot_id if prior_on_thread else None
    )

    payload = build_staging_snapshot_payload(
        build_candidate=bc,
        evaluation_report=ev,
        thread=thread,
        build_spec=spec,
        prior_staging_snapshot_id=prior_staging_id,
    )
    ssid = uuid4()
    return StagingSnapshotRecord(
        staging_snapshot_id=ssid,
        thread_id=bc.thread_id,
        build_candidate_id=bc.build_candidate_id,
        graph_run_id=bc.graph_run_id,
        identity_id=thread.identity_id,
        prior_staging_snapshot_id=prior_staging_id,
        snapshot_payload_json=payload,
        preview_url=bc.preview_url,
        status="review_ready",
        marked_for_review=False,
        mark_reason=None,
        review_tags=[],
    )
