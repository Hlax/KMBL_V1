# Pass L: Operator action visibility (runtime read model + UI)

Lightweight **persisted** visibility for operator-triggered runtime mutations on graph run detail. Derivation uses **`graph_run_event`** rows only — no websockets/SSE, no optimistic UI, and **no new mutation endpoints** in this pass.

## Files changed

### Orchestrator

- `services/orchestrator/src/kmbl_orchestrator/runtime/operator_action_read_model.py` — whitelist of operator event types; `build_operator_actions_from_events`, `resume_stats_from_events`, `is_operator_triggered_event`.
- `services/orchestrator/src/kmbl_orchestrator/runtime/graph_run_detail_read_model.py` — merges `operator_actions`, summary `resume_count` / `last_resumed_at`, timeline `operator_triggered`.
- `services/orchestrator/src/kmbl_orchestrator/api/main.py` — Pydantic models: `GraphRunSummaryBlock` (resume fields), `OperatorActionItem`, `RunTimelineItem.operator_triggered`, `GraphRunDetailResponse.operator_actions`.
- `services/orchestrator/tests/test_operator_visibility_pass_l.py` — API contract for resume + operator flags.

### Control plane

- `apps/control-plane/lib/api-types.ts` — `OperatorActionItem`; optional fields on `GraphRunSummaryBlock`, `RunTimelineItem`, `GraphRunDetail`.
- `apps/control-plane/app/runs/[graphRunId]/page.tsx` — Run summary rows; **Operator actions** panel (empty state); timeline badge + `op-timeline__operator` styling hook.
- `apps/control-plane/app/globals.css` — `.op-badge--operator`, `.op-timeline li.op-timeline__operator::before`.

## Operator-action derivation rules

- Only event types in `OPERATOR_TRIGGERED_EVENT_TYPES` are treated as operator-triggered. **Currently:** `graph_run_resumed` only.
- **Do not** infer operator intent from generic graph/system events (checkpoints, planner steps, etc.).
- **`operator_actions[]`:** one entry per matching event, ordered by `created_at` ascending (aligned with timeline order). Fields: `kind`, `label`, `timestamp`, optional `details` (small whitelist from payload, e.g. `basis` when present).
- **`resume_count` / `last_resumed_at`:** derived only from `graph_run_resumed` events (count and max timestamp).

## Summary fields added

On **GET** `/orchestrator/runs/{graph_run_id}/detail`, inside `summary`:

| Field | Meaning |
| --- | --- |
| `resume_count` | Number of persisted `graph_run_resumed` events. |
| `last_resumed_at` | ISO timestamp of the latest `graph_run_resumed`, or `null`. |

Top-level `operator_actions` mirrors the filtered operator-only view (not full event payloads).

## Manual verification checklist

1. Open `/runs/[graphRunId]` for a run with **no** resume events: **Operator actions** shows empty copy; summary shows `resume_count` 0 and `last_resumed_at` as em dash; timeline has no orange operator markers.
2. Trigger **Resume** (Pass K) once, reload: summary shows `resume_count` 1 and `last_resumed_at`; **Operator actions** lists one row; timeline row for resume shows **operator** badge and orange dot.
3. Confirm full timeline still lists all persisted events; operator section is a **subset**, not a duplicate of large payloads.
4. `npm run build` in `apps/control-plane` succeeds; `pytest` for orchestrator passes.

## Known limitations

- **Single operator event type** in the whitelist; future operator APIs should append explicit event types and extend `OPERATOR_TRIGGERED_EVENT_TYPES` rather than heuristics.
- **Runs index** (`GET /orchestrator/runs`) is unchanged — resume stats are on **detail** only (modest scope).
- **Retry** and bulk actions are out of scope (Pass L is read-only for new behavior).

## Pass F note

Duplicate-publication and staging/publication read paths were **not** modified for Pass L.
