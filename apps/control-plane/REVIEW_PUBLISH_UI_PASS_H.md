# Review / publish UI — Pass H (run detail surface)

## Goal

Bridge **runtime execution** and **review surfaces** with a minimal, **persisted-only** run detail page. No live streaming, websockets, SSE, or polling-heavy dashboards.

## Files changed

### Orchestrator

- `services/orchestrator/src/kmbl_orchestrator/runtime/graph_run_detail_read_model.py` — read-model builder (`summary`, `role_invocations`, `associated_outputs`, `timeline`).
- `services/orchestrator/src/kmbl_orchestrator/api/main.py` — `GET /orchestrator/runs/{graph_run_id}/detail` → `GraphRunDetailResponse`.
- `services/orchestrator/src/kmbl_orchestrator/persistence/repository.py` — protocol + in-memory: `list_role_invocations_for_graph_run`, `list_staging_snapshots_for_graph_run`, `list_publications_for_graph_run`, `get_latest_checkpoint_for_graph_run`.
- `services/orchestrator/src/kmbl_orchestrator/persistence/supabase_repository.py` — same methods for Supabase.
- `services/orchestrator/tests/test_graph_run_detail_pass_h.py` — endpoint smoke tests.

### Control plane

- `apps/control-plane/app/api/runs/[graphRunId]/route.ts` — proxy to orchestrator detail URL.
- `apps/control-plane/app/runs/[graphRunId]/page.tsx` — operator run detail UI.
- `apps/control-plane/app/review/staging/[stagingSnapshotId]/page.tsx` — lineage `graph_run_id` links to `/runs/[graphRunId]` when present.
- `apps/control-plane/lib/api-types.ts` — `GraphRunDetail` and nested types.
- `apps/control-plane/app/globals.css` — `op-banner--neutral`, `op-badge--neutral`, compact `op-table` styles.

## API added / changed

| Method | Path | Notes |
|--------|------|--------|
| `GET` | `/orchestrator/runs/{graph_run_id}/detail` | **New.** Compact read model. Does **not** replace `GET /orchestrator/runs/{graph_run_id}` (`RunStatusResponse` with snapshot). |

### Response shape (`GraphRunDetailResponse`)

- `summary` — `graph_run_id`, `thread_id`, `identity_id` (if thread has one), `trigger_type`, `status`, `started_at`, `ended_at`, `max_iteration_index`, `latest_checkpoint_id`, `run_state_hint`.
- `role_invocations` — ordered by **`started_at` ascending** (execution order).
- `associated_outputs` — latest build_spec / build_candidate / evaluation for the run when present; **newest** staging and publication rows matching `graph_run_id` (see repository ordering below).
- `timeline` — from `graph_run_event` rows only, sorted by `created_at` ascending.
- `basis`: always `"persisted_rows_only"`.

## Repository assumptions

- **Role invocations**: `list_role_invocations_for_graph_run` returns rows for the run, ordered **oldest `started_at` first** (in-memory and Supabase aligned).
- **Staging**: `list_staging_snapshots_for_graph_run` filters `staging_snapshot.graph_run_id`, **newest `created_at` first**; associated output uses index `0` as “latest” for this run.
- **Publications**: `list_publications_for_graph_run` filters `publication_snapshot.graph_run_id`, **newest `published_at` first**; associated `publication_snapshot_id` uses index `0` only when such a row exists (explicit persisted relation — not guessed from staging).
- **Checkpoint**: `get_latest_checkpoint_for_graph_run` returns the checkpoint with the latest `created_at` for that `graph_run_id`, if any.

## Event timeline derivation rules

- Timeline items are built **only** from `list_graph_run_events` results (persisted `graph_run_event` rows).
- Each row maps to `kind`, human `label`, `timestamp` (`created_at`), optional `related_id` (e.g. staging/publication ids from event payload when present), and raw `event_type`.
- Unknown event types still appear with `kind` `"event"` and `label` = stored `event_type` string.
- No synthetic events: if nothing was persisted, the timeline is empty.

## Manual verification checklist

1. Start orchestrator and control plane with `NEXT_PUBLIC_ORCHESTRATOR_URL` set.
2. Open a staging snapshot that has `lineage.graph_run_id` (e.g. from `/review/staging/{id}`).
3. Confirm **graph_run_id** in lineage is a link to `/runs/{graphRunId}` and matches the plain UUID text.
4. On `/runs/{graphRunId}`, confirm **Run summary**, **Event timeline**, **Role invocations**, **Associated outputs** (staging link if id present).
5. Expand **Raw JSON** and confirm it matches the API (no unexpected large provider blobs in top-level fields).
6. Confirm **no** websocket/SSE/new polling loops were added for this page.

## Known limitations

- **`GET /orchestrator/runs/{id}`** remains the full **run status** response (including snapshot). Detail is a **separate** route to avoid duplicating large payloads.
- Timeline may be **truncated** by `list_graph_run_events(..., limit=500)` in the handler — very chatty runs may not show every event.
- **Publication** on the run detail page appears only when a `publication_snapshot` row exists with the same `graph_run_id`; publishing only from staging linkage without `graph_run_id` on the publication row will not surface here.
- **Not live**: status reflects last persisted rows; refreshing the page re-fetches the same persisted view.
