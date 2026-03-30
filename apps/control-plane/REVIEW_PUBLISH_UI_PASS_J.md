# Review / publish UI — Pass J (operator attention)

## Goal

Add **lightweight, persisted-only** attention/triage indicators on runtime and review surfaces so operators can prioritize work — **no new mutations**, websockets, or live polling.

## Files changed

### Orchestrator

- `services/orchestrator/src/kmbl_orchestrator/runtime/graph_run_attention.py` — `derive_graph_run_attention`.
- `services/orchestrator/src/kmbl_orchestrator/staging/review_action.py` — `derive_review_action_state`, `review_action_sort_key`.
- `services/orchestrator/src/kmbl_orchestrator/runtime/graph_run_list_read_model.py` — adds `attention_state` / `attention_reason` per row.
- `services/orchestrator/src/kmbl_orchestrator/runtime/graph_run_detail_read_model.py` — same fields on `summary`.
- `services/orchestrator/src/kmbl_orchestrator/persistence/repository.py` — `publication_counts_for_staging_snapshot_ids`.
- `services/orchestrator/src/kmbl_orchestrator/persistence/supabase_repository.py` — same.
- `services/orchestrator/src/kmbl_orchestrator/api/main.py` — `GraphRunSummaryBlock` / `GraphRunListItem` extended; `GET /orchestrator/proposals` uses all staging statuses + publication counts + sort.
- `services/orchestrator/tests/test_operator_attention_pass_j.py`
- Updates: `test_graph_run_detail_pass_h.py`, `test_graph_run_list_pass_i.py`, `test_review_layer_pass_c.py`

### Control plane

- `apps/control-plane/lib/operator-attention.ts` — UI helpers (classes/labels only).
- `apps/control-plane/lib/api-types.ts` — attention + review action fields.
- `apps/control-plane/app/runs/page.tsx` — attention column.
- `apps/control-plane/app/runs/[graphRunId]/page.tsx` — attention banner + summary field.
- `apps/control-plane/app/review/page.tsx` — action badges, linked publication count, copy.
- `apps/control-plane/app/globals.css` — attention banner + badge styles.

## Derived graph run attention states

| `attention_state` | When (persisted only) |
|---------------------|------------------------|
| `needs_investigation` | `graph_run.status == failed` |
| `waiting_on_resume` | `status == paused` |
| `interrupt_signal` | `status == running` and interrupt checkpoint has `orchestrator_error` dict (same signal as `run_state_hint`) |
| `completed_no_staging` | `status == completed` and no staging row for this `graph_run_id` |
| `healthy` | Otherwise |

Each row includes `attention_reason` (short operator text).

## Review queue (`GET /orchestrator/proposals`)

| `review_action_state` | When |
|------------------------|------|
| `published` | `linked_publication_count > 0` |
| `ready_for_review` | No pubs and `staging.status == review_ready` |
| `ready_to_publish` | No pubs and `staging.status == approved` |
| `not_actionable` | Other statuses (e.g. archived) |

**Sorting**: tier order `ready_for_review` → `ready_to_publish` → `published` → `not_actionable`; within a tier, **newer `created_at` first** (ISO timestamps).

Response includes `basis: "persisted_rows_only"` and per-row `linked_publication_count`, `review_action_state`, `review_action_reason`.

## Manual verification checklist

1. `/runs` — attention column shows state; tooltip (title) shows reason.
2. `/runs/[id]` — banner is **warn** styling unless `healthy`; neutral banner still explains persisted-only context.
3. `/review` — cards show action badge + reason; order matches tiers (e.g. `review_ready` before archived).
4. No new buttons or mutation APIs; no websockets/SSE added.

## Known limitations

- Attention does **not** reconcile stale `running` rows (same as Pass I list).
- **Proposals** list is capped by `limit` (default 20) across **all** statuses — very busy environments may need a higher limit or future paging.
- UI labels in `operator-attention.ts` are presentation-only; server strings remain authoritative.

## Exact test steps

```bash
cd services/orchestrator
python -m pytest tests/test_operator_attention_pass_j.py tests/test_graph_run_detail_pass_h.py tests/test_graph_run_list_pass_i.py tests/test_review_layer_pass_c.py -q
```

```bash
cd apps/control-plane
npm run build
```
