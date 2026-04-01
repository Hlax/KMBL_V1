"""Pass J — attention derivation from persisted-shaped inputs only."""

from __future__ import annotations

from uuid import uuid4

from kmbl_orchestrator.domain import StagingSnapshotRecord
from kmbl_orchestrator.runtime.graph_run_attention import derive_graph_run_attention
from kmbl_orchestrator.staging.review_action import (
    derive_review_action_state,
    review_action_sort_key,
)


def test_graph_run_attention_priority_failed_over_interrupt() -> None:
    st, _ = derive_graph_run_attention(
        status="failed",
        has_interrupt_signal=True,
        latest_staging_snapshot_id=None,
    )
    assert st == "needs_investigation"


def test_graph_run_attention_completed_no_staging() -> None:
    st, reason = derive_graph_run_attention(
        status="completed",
        has_interrupt_signal=False,
        latest_staging_snapshot_id=None,
    )
    assert st == "completed_no_staging"
    assert "staging" in reason.lower()


def test_graph_run_attention_completed_snapshot_skipped_by_policy() -> None:
    st, reason = derive_graph_run_attention(
        status="completed",
        has_interrupt_signal=False,
        latest_staging_snapshot_id=None,
        snapshot_skipped_intentionally=True,
    )
    assert st == "completed_snapshot_skipped_by_policy"
    assert "policy" in reason.lower()


def test_review_action_published_wins_over_status() -> None:
    rec = StagingSnapshotRecord(
        staging_snapshot_id=uuid4(),
        thread_id=uuid4(),
        build_candidate_id=uuid4(),
        snapshot_payload_json={},
        status="review_ready",
    )
    st, _ = derive_review_action_state(rec, linked_publication_count=1)
    assert st == "published"


def test_review_action_sort_key_order() -> None:
    assert review_action_sort_key("ready_for_review", "2026-01-01")[0] < review_action_sort_key(
        "published", "2026-01-01"
    )[0]
