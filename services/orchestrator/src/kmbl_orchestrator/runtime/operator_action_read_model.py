"""Pass L — operator-triggered actions derived from graph_run_event rows only."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.domain import GraphRunEventRecord
from kmbl_orchestrator.runtime.run_events import RunEventType

# Event types that are explicitly written for operator/API actions (not generic graph noise).
OPERATOR_TRIGGERED_EVENT_TYPES: frozenset[str] = frozenset(
    {
        RunEventType.GRAPH_RUN_RESUMED,
    }
)


def _action_label_and_kind(event_type: str) -> tuple[str, str]:
    if event_type == RunEventType.GRAPH_RUN_RESUMED:
        return "graph_run_resumed", "Resume (operator)"
    return event_type, event_type


def build_operator_actions_from_events(
    events: list[GraphRunEventRecord],
) -> list[dict[str, Any]]:
    """Ordered by ``created_at`` ascending (same as timeline)."""
    rows: list[GraphRunEventRecord] = sorted(events, key=lambda e: e.created_at)
    out: list[dict[str, Any]] = []
    for e in rows:
        if e.event_type not in OPERATOR_TRIGGERED_EVENT_TYPES:
            continue
        kind, label = _action_label_and_kind(e.event_type)
        payload = dict(e.payload_json or {})
        d = {k: payload[k] for k in ("basis",) if k in payload}
        details: dict[str, Any] | None = d if d else None
        out.append(
            {
                "kind": kind,
                "label": label,
                "timestamp": e.created_at,
                "details": details,
            }
        )
    return out


def resume_stats_from_events(events: list[GraphRunEventRecord]) -> tuple[int, str | None]:
    """Count and latest ``created_at`` for ``graph_run_resumed`` events."""
    resumed = [
        e.created_at
        for e in events
        if e.event_type == RunEventType.GRAPH_RUN_RESUMED
    ]
    if not resumed:
        return 0, None
    resumed.sort()
    return len(resumed), resumed[-1]


def is_operator_triggered_event(event_type: str) -> bool:
    return event_type in OPERATOR_TRIGGERED_EVENT_TYPES
