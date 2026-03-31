"""Strip LangGraph checkpoint blobs from public GET /orchestrator/runs/{id} responses."""

from __future__ import annotations

from typing import Any

# Keys that are safe to expose from persisted graph state (no embedded role / KiloClaw blobs).
_SAFE_SCALAR_KEYS: frozenset[str] = frozenset(
    {
        "thread_id",
        "graph_run_id",
        "identity_id",
        "trigger_type",
        "iteration_index",
        "max_iterations",
        "decision",
        "status",
        "interrupt_reason",
        "staging_snapshot_id",
        "build_spec_id",
        "build_candidate_id",
        "evaluation_report_id",
        "last_alignment_score",
    }
)


def sanitize_checkpoint_state_for_api(state: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Return a small, product-facing subset of the post-role checkpoint.

    Omits ``build_spec``, ``build_candidate``, ``evaluation_report`` dicts,
    identity/memory context, and other fields that duplicate provider payloads.
    """
    if not state:
        return None
    out: dict[str, Any] = {}
    for k in _SAFE_SCALAR_KEYS:
        if k not in state:
            continue
        v = state[k]
        if v is None or isinstance(v, (str, int, float, bool)):
            out[k] = v
    ev = state.get("event_input")
    if isinstance(ev, dict):
        slim: dict[str, Any] = {}
        if "scenario" in ev:
            slim["scenario"] = ev["scenario"]
        c = ev.get("constraints")
        if isinstance(c, dict):
            slim_c: dict[str, Any] = {}
            if "deterministic" in c:
                slim_c["deterministic"] = c["deterministic"]
            if "gallery_variation_mode" in c:
                slim_c["gallery_variation_mode"] = c["gallery_variation_mode"]
            if slim_c:
                slim["constraints"] = slim_c
        var = ev.get("variation")
        if isinstance(var, dict):
            slim["variation"] = var
        if slim:
            out["event_input"] = slim
    # Bounded list: per-iteration alignment snapshots (no role payloads).
    ash = state.get("alignment_score_history")
    if isinstance(ash, list) and ash:
        out["alignment_score_history"] = ash[-20:]
    return out
