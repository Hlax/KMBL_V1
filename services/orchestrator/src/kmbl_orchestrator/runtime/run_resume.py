"""Operator resume eligibility — determines whether a graph run can be re-executed."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from kmbl_orchestrator.persistence.repository import Repository

# Must match ``orchestrator_error.error_kind`` written by stale_run reconciliation.
STALE_RUN_ERROR_KIND = "orchestrator_stale_run"


def compute_resume_eligibility(
    repo: Repository,
    graph_run_id: UUID,
) -> tuple[bool, str | None]:
    """
    Return (eligible, explanation when eligible, or None).

    Ineligible cases return (False, human-readable reason for 409).
    """
    gr = repo.get_graph_run(graph_run_id)
    if gr is None:
        return False, "graph_run not found"

    if gr.status == "completed":
        return False, "Run already completed — nothing to resume."

    if gr.status == "running":
        return (
            False,
            "Run is still marked running; wait for completion or stale reconciliation.",
        )

    if gr.status == "paused":
        return (
            True,
            "Run is paused — resume re-queues graph execution for this graph_run_id.",
        )

    if gr.status == "failed":
        err = repo.get_latest_interrupt_orchestrator_error(graph_run_id)
        ek = err.get("error_kind") if isinstance(err, dict) else None
        if ek == STALE_RUN_ERROR_KIND:
            return (
                True,
                "Run failed as stale (orchestrator timeout) — resume re-executes once for this id.",
            )
        return (
            False,
            "Failed for a reason other than stale timeout — generic retry is not implemented.",
        )

    return False, f"Status {gr.status!r} is not eligible for resume."


def event_input_for_resume(repo: Repository, graph_run_id: UUID) -> dict[str, Any]:
    """Best-effort ``event_input`` from latest run snapshot (persisted)."""
    snap = repo.get_run_snapshot(graph_run_id)
    if not isinstance(snap, dict):
        return {}
    ei = snap.get("event_input")
    return dict(ei) if isinstance(ei, dict) else {}
