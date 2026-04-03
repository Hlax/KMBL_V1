# Cross-run memory and taste

KMBL persists **explainable**, **typed** memory per `identity_id` so future runs can bias planning without hidden autonomy. This is not a recommendation engine or long-term planner.

## Storage

Table `identity_cross_run_memory` (see migration `20260402120000_identity_cross_run_memory.sql`):

- **Scope**: Rows are keyed by `(identity_id, category, memory_key)` — unique merge key.
- **Categories** (conceptually separate):
  - `identity_derived` — stable tendencies from structured identity extraction when confidence is high enough.
  - `run_outcome` — compact aggregates from completed graph runs (eval status, experience_mode, rescue counts, mutation hints).
  - `operator_confirmed` — stronger signals from **existing** operator actions: staging approval and publication creation (no synthetic approval).

Thread-only state is **not** promoted to durable preference memory unless an explicit operator or completion path writes it.

## Read path

On each run, `context_hydrator` loads rows for the identity and injects `memory_context.cross_run`:

- `taste_summary` — aggregated preferences (operator > identity > run outcome on conflicts).
- `prompt_hints` — short lines for the planner payload.
- `items` / `read_trace` — what was considered and why.

`planner_node` may **bias** `experience_mode` when structured-identity confidence is low and taste/operator memory strongly prefers another mode. Planner-set `experience_mode` is never overwritten.

## Write path

| Trigger | Module | Notes |
|--------|--------|--------|
| Hydration + threshold | `memory.ops.maybe_write_identity_derived_memory` | identity_derived keys `likely_experience_mode`, `visual_style_hints` |
| Graph completion | `memory.ops.record_run_outcome_memory` | merges `aggregate_run_outcome` |
| POST staging approve | `record_operator_memory_from_staging_approval` | boosts `preferred_experience_mode` |
| POST publication | `record_operator_memory_from_publication` | stronger boost + optional `aesthetic_taste` from snapshot payload |

Append-only `graph_run_event` rows `cross_run_memory_loaded` / `cross_run_memory_updated` record influence for operators.

## Guardrails

Configured via `Settings` (`memory_*` keys in `config.py`):

- Strength clamps and small per-write deltas so one failed run cannot dominate.
- Optional freshness decay on read (`memory_freshness_half_life_days`).
- Soft cap on rows per identity (`memory_max_keys_per_identity`).

## API visibility

`GET /orchestrator/runs/{id}/detail` includes `memory_influence`: event-derived payloads, keys persisted with `source_graph_run_id = this run`, and an optional `identity_taste_summary`.

## Follow-ups

- Optional `scope_key` (e.g. normalized source URL) for finer-grained memory.
- Control-plane UI polish for `memory_influence`.
- Tuning evaluator-nomination vs run_outcome weighting.
