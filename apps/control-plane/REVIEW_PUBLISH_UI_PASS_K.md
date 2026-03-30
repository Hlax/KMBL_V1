# Review / publish UI — Pass K (runtime actions)

## Goal

Add the **smallest safe** operator actions for graph runs from the **run detail** page: **Resume** for eligible persisted states. **Retry** is explicitly deferred.

## Files changed

### Orchestrator

- `services/orchestrator/src/kmbl_orchestrator/runtime/run_resume.py` — `compute_resume_eligibility`, `event_input_for_resume`, `STALE_RUN_ERROR_KIND`.
- `services/orchestrator/src/kmbl_orchestrator/runtime/run_events.py` — `GRAPH_RUN_RESUMED`.
- `services/orchestrator/src/kmbl_orchestrator/persistence/repository.py` — `mark_graph_run_resuming` (in-memory).
- `services/orchestrator/src/kmbl_orchestrator/persistence/supabase_repository.py` — `mark_graph_run_resuming` (clears `ended_at`).
- `services/orchestrator/src/kmbl_orchestrator/api/main.py` — `POST /orchestrator/runs/{graph_run_id}/resume`, `ResumeRunResponse`, `GraphRunDetailResponse` extended with `resume_eligible`, `resume_operator_explanation`, `retry_eligible`, `retry_deferred_note`.
- `services/orchestrator/tests/test_resume_pass_k.py`

### Control plane

- `apps/control-plane/app/api/runs/[graphRunId]/resume/route.ts` — POST proxy.
- `apps/control-plane/app/runs/[graphRunId]/RunResumeActions.tsx` — Resume button + disabled Retry + inline messages + `router.refresh()`.
- `apps/control-plane/app/runs/[graphRunId]/page.tsx` — mounts actions.
- `apps/control-plane/lib/api-types.ts` — detail fields for resume/retry metadata.

## Mutation endpoints

| Method | Path | Purpose |
|--------|------|--------|
| `POST` | `/orchestrator/runs/{graph_run_id}/resume` | Operator resume: mark run `running`, clear `ended_at`, append `graph_run_resumed` event, enqueue `_run_graph_background` with `trigger_type=resume` and best-effort `event_input` from persisted snapshot. |

**Retry:** not implemented (`retry_eligible` is always `false` in this release).

## Eligibility rules

After `reconcile_stale_running_graph_run` (same as GET detail):

1. **`paused`** — eligible. Re-queues execution for the **same** `graph_run_id` (not a new run).
2. **`failed`** — eligible **only** if the latest interrupt checkpoint’s `orchestrator_error.error_kind` is **`orchestrator_stale_run`** (stale-timeout failure from `stale_run` reconciliation).
3. **`running`** — not eligible (409: still executing or needs reconciliation).
4. **`completed`** — not eligible.

Explanations are returned on the detail read model as `resume_operator_explanation` (both when eligible and when not, for operator copy).

## Error behavior

- **409** `resume_not_eligible` with `detail.message` when resume is not allowed.
- **404** if `graph_run_id` missing.
- **400** invalid UUID.

## Read-model / refresh

- Control plane **does not** optimistically patch status; after Resume, the client calls **`router.refresh()`** so the server component re-fetches **`GET /api/runs/{id}`** (orchestrator detail).

## Manual verification checklist

1. Open `/runs/{id}` for a **paused** run (or stale-failed run) — Resume enabled when `resume_eligible` is true on detail JSON.
2. POST resume — orchestrator returns 200; refresh shows updated persisted status (may become `running`, then `completed`/`failed` after background graph).
3. POST resume on **completed** — 409.
4. No new WebSockets/SSE; `/runs` list unchanged (no actions there).

## Known limitations

- **Not checkpoint replay**: resume calls `run_graph` again with the same ids; LangGraph still starts from compiled graph entry — behavior is “re-execute for this `graph_run_id`,” not mid-graph rewind.
- **Generic failed runs** (non-stale) cannot be resumed or retried from this pass.
- **Double resume** while `running` is rejected; race if two tabs click quickly is not fully serialized beyond 409 on second call when state updates.

## Exact test steps

```bash
cd services/orchestrator
python -m pytest tests/test_resume_pass_k.py -q
```

```bash
cd apps/control-plane
npm run build
```
