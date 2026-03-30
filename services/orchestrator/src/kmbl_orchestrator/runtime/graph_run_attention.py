"""Pass J — operator attention for graph runs (persisted fields only)."""

from __future__ import annotations


def derive_graph_run_attention(
    *,
    status: str,
    has_interrupt_signal: bool,
    latest_staging_snapshot_id: str | None,
) -> tuple[str, str]:
    """
    Return (attention_state, attention_reason).

    Priority: failed → paused → running+interrupt → completed without staging → healthy.
    Uses the same interrupt signal as ``run_state_hint`` (interrupt checkpoint payload).
    """
    if status == "failed":
        return (
            "needs_investigation",
            "Run failed — check timeline and role errors.",
        )
    if status == "paused":
        return (
            "waiting_on_resume",
            "Run is paused — may need resume or operator review.",
        )
    if status == "running" and has_interrupt_signal:
        return (
            "interrupt_signal",
            "Interrupt checkpoint with orchestrator context — may await resume.",
        )
    if status == "completed" and not latest_staging_snapshot_id:
        return (
            "completed_no_staging",
            "Completed but no staging snapshot linked to this run id.",
        )
    return (
        "healthy",
        "No immediate operator attention indicated.",
    )
