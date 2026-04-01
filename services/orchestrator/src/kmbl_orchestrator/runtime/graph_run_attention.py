"""Graph run attention — derives operator attention flags from persisted graph run fields."""

from __future__ import annotations


def derive_graph_run_attention(
    *,
    status: str,
    has_interrupt_signal: bool,
    latest_staging_snapshot_id: str | None,
    snapshot_skipped_intentionally: bool = False,
) -> tuple[str, str]:
    """
    Return (attention_state, attention_reason).

    Priority: failed → paused → running+interrupt → completed without staging → healthy.
    Uses the same interrupt signal as ``run_state_hint`` (interrupt checkpoint payload).

    When ``snapshot_skipped_intentionally`` is true (e.g. ``staging_snapshot_policy`` is
    ``on_nomination`` / ``never`` and staging emitted ``staging_snapshot_skipped``),
    a completed run without a frozen ``staging_snapshot`` row is expected — working
    staging may still hold the latest build.
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
    if status == "interrupt_requested":
        return (
            "interrupt_pending",
            "Interrupt requested — run will stop at the next cooperative boundary.",
        )
    if status == "interrupted":
        return (
            "interrupted",
            "Run was stopped cooperatively by operator request.",
        )
    if status == "running" and has_interrupt_signal:
        return (
            "interrupt_signal",
            "Interrupt checkpoint with orchestrator context — may await resume.",
        )
    if status == "completed" and not latest_staging_snapshot_id:
        if snapshot_skipped_intentionally:
            return (
                "completed_snapshot_skipped_by_policy",
                "No frozen review snapshot for this run — automatic snapshot was skipped by policy; live working staging may still hold the latest build. Use “Materialize review snapshot” from live habitat if you need a review row.",
            )
        return (
            "completed_no_staging",
            "Completed but no staging snapshot linked to this run id.",
        )
    return (
        "healthy",
        "No immediate operator attention indicated.",
    )
