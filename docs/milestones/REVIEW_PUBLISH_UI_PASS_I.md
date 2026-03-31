# Review / publish UI — Pass I (runs index)

## Goal

Add a **lightweight persisted runs index** so operators can browse recent runtime execution, apply basic filters, and open run detail or linked staging — without live streaming, websockets, SSE, or heavy polling.

## Files changed

### Orchestrator

- `services/orchestrator/src/kmbl_orchestrator/persistence/repository.py` — protocol + in-memory:
  - `list_graph_runs` (optional `status`, `trigger_type`, `identity_id`, `limit`)
  - `aggregate_role_invocation_stats_for_graph_runs`
  - `latest_staging_snapshot_ids_for_graph_runs`
  - `graph_run_ids_with_interrupt_orchestrator_error`
- `services/orchestrator/src/kmbl_orchestrator/persistence/supabase_repository.py` — same methods for Supabase.
- `services/orchestrator/src/kmbl_orchestrator/runtime/graph_run_list_read_model.py` — `build_graph_run_list_read_model`.
- `services/orchestrator/src/kmbl_orchestrator/api/main.py` — `GET /orchestrator/runs`, Pydantic `GraphRunListResponse`.
- `services/orchestrator/tests/test_graph_run_list_pass_i.py`

### Control plane

- `apps/control-plane/app/api/runs/route.ts` — GET proxy (forwards query string to orchestrator).
- `apps/control-plane/app/runs/page.tsx` — `/runs` index (table + filter form).
- `apps/control-plane/app/components/ControlPlaneNav.tsx` — **Runs** link.
- `apps/control-plane/app/runs/[graphRunId]/page.tsx` — breadcrumb includes **Runs**.
- `apps/control-plane/lib/api-types.ts` — `GraphRunListItem`, `GraphRunListResponse`.
- `apps/control-plane/app/globals.css` — `.op-runs-filters__row`.

## API added / changed

| Method | Path | Notes |
|--------|------|--------|
| `GET` | `/orchestrator/runs` | **New.** Compact list; does **not** replace `GET /orchestrator/runs/{id}` or `/detail`. |

### Query parameters

| Param | Description |
|--------|----------------|
| `status` | Optional — `running` \| `paused` \| `completed` \| `failed` |
| `trigger_type` | Optional — `prompt` \| `resume` \| `schedule` \| `system` |
| `identity_id` | Optional UUID — filters runs whose **thread** has this `identity_id` |
| `limit` | Default **50**, max **200** (server-capped) |

Empty or whitespace-only string params are treated as “not set.”

### Response (`GraphRunListResponse`)

- `runs[]`: `graph_run_id`, `thread_id`, `identity_id` (from thread), `trigger_type`, `status`, `started_at`, `ended_at`, `max_iteration_index`, `run_state_hint` (same semantics as Pass H detail), `role_invocation_count`, `latest_staging_snapshot_id` (newest staging row for that `graph_run_id`, if any).
- `count`, `basis`: `"persisted_rows_only"`.

## Filter behavior

- **Ordering**: newest **`started_at` first** (repository contract).
- **identity_id**: resolves via `thread.identity_id`; runs with no matching threads return an empty list.
- **No stale reconciliation** on this endpoint — list reflects stored `graph_run` rows as-is. Open a specific run’s status/detail routes to reconcile a stale `running` row if needed.

## Repository assumptions

- **list_graph_runs**: filters apply to `graph_run` rows; `identity_id` restricts to `thread_id` values whose `thread` row has that `identity_id`.
- **Role stats**: from `role_invocation` rows — `(count, max(iteration_index))` per run.
- **Latest staging**: newest `staging_snapshot.created_at` among rows with that `graph_run_id` (null `graph_run_id` excluded).
- **Interrupt hint**: same as Pass H — latest **interrupt** checkpoint’s `state_json.orchestrator_error` being a dict implies “interrupt signal” for `run_state_hint` on **running** runs.

## Manual verification checklist

1. Set `NEXT_PUBLIC_ORCHESTRATOR_URL`; run orchestrator and control plane.
2. Open **`/runs`** — table loads (may be empty).
3. Start or seed runs; confirm rows appear, **graph_run_id** links to **`/runs/{id}`**.
4. When staging exists for a run, **staging** column links to **`/review/staging/{id}`**.
5. Use filters (status, trigger, identity UUID, limit); URL updates via **`GET /runs?...`** (form method=get).
6. Confirm **Runs** appears in the top nav next to Review / Publication.
7. No new websockets/SSE/live streaming.

## Known limitations

- List does **not** reconcile stale `running` rows (by design — cheap read).
- **Supabase** `list_graph_runs` caps internal fetch at 500 rows max in repo layer; API **`limit`** max is 200.
- **Performance**: enrichment uses batched queries (stats, staging, interrupts) over the returned id set — not one round-trip per row, but not a single SQL view either.

## Exact test steps (automated)

From repo root (or `services/orchestrator`):

```bash
python -m pytest services/orchestrator/tests/test_graph_run_list_pass_i.py -q
```

Control plane:

```bash
cd apps/control-plane && npm run build
```
