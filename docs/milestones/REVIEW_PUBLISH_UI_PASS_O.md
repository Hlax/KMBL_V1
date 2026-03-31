# Pass O: Control-plane home summary

Lightweight **persisted-only** operator dashboard on `/` — three summary cards (Runtime, Review queue, Canon) with links to `/runs`, `/review`, and `/publication`. No streaming, no polling, no new mutations.

## Files changed

### Orchestrator

- `services/orchestrator/src/kmbl_orchestrator/runtime/operator_home_summary.py` *(new)* — aggregates bounded windows of `graph_run` and `staging_snapshot` rows + latest publication.
- `services/orchestrator/src/kmbl_orchestrator/api/main.py` — `GET /orchestrator/operator-summary`, Pydantic models `OperatorHomeSummaryResponse` and nested blocks.
- `services/orchestrator/tests/test_operator_home_pass_o.py` *(new)*

### Control plane

- `apps/control-plane/app/api/operator-summary/route.ts` *(new)* — proxy to orchestrator.
- `apps/control-plane/app/page.tsx` — async server-rendered home with three cards.
- `apps/control-plane/lib/api-types.ts` — `OperatorHomeSummary` type.
- `apps/control-plane/app/globals.css` — `.op-home-dashboard`, `.op-home-card-grid`, card tweaks.

## Summary fields shown

### Runtime

| Field | Source |
| --- | --- |
| `runs_in_window` | Count of rows in the graph-run list read model (up to **200** most recent by `started_at`). |
| `runs_needing_attention` | Runs where `attention_state` ≠ `healthy` (same derivation as Pass J list). |
| `failed_count` | `status == failed`. |
| `paused_count` | `status == paused`. |

### Review queue

| Field | Source |
| --- | --- |
| `ready_for_review`, `ready_to_publish`, `published`, `not_actionable` | Derived per staging row via `derive_review_action_state` + publication counts, over up to **500** recent staging snapshots (`created_at` desc). |

### Canon

| Field | Source |
| --- | --- |
| `has_current_publication` | `get_latest_publication_snapshot(identity_id=None)` is not `None`. |
| `latest_publication_snapshot_id`, `latest_published_at` | From that latest row. |

## Data sourcing approach

- **Single modest endpoint** `GET /orchestrator/operator-summary` returns compact JSON (`basis: persisted_rows_only`).
- Control plane **GET `/api/operator-summary`** proxies to the orchestrator (same pattern as other routes).
- Home page is a **server component** that fetches once per request (`cache: "no-store"`).

## Manual verification checklist

1. With orchestrator running and data present, open `/` — three cards show numbers and links work.
2. Click **Runtime** / **Open runs** → `/runs`.
3. Click **Review queue** → `/review`.
4. Click **Canon** / publication id → `/publication/[id]` when a publication exists.
5. With empty DB, cards show zeros / “none” for canon without errors.
6. `npm run build` in `apps/control-plane` succeeds; `pytest services/orchestrator/tests/test_operator_home_pass_o.py` passes.

## Known limitations

- Counts are **windowed** (200 runs, 500 staging rows), not global table totals — appropriate for orientation, not analytics.
- Staging ordering is “recent snapshots”; review-tier counts may omit very old rows if the table is huge.
- **Pass F** duplicate-publication rules are unchanged (endpoint is read-only).

## Pass F

No changes to publication creation, eligibility, or duplicate detection.
