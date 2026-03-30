# Pass N: Review queue filters and sorting

Lightweight **persisted-only** filtering and sorting on the proposals endpoint (`GET /orchestrator/proposals`) and a **GET form** on `/review` that mirrors the `/runs` pattern. No mutations, no streaming, no change to Pass F duplicate-publication rules.

## Files changed

### Orchestrator

- `services/orchestrator/src/kmbl_orchestrator/staging/proposals_queue.py` *(new)* — blank normalization, `has_publication` tri-state, `sort` modes, wide-pool `fetch_limit`, filter + in-place sort helpers.
- `services/orchestrator/src/kmbl_orchestrator/api/main.py` — `list_proposals` extended with query params; uses wider staging fetch (up to 500, repo cap) when derived filters or non-default sort require it.
- `services/orchestrator/tests/test_proposals_queue_pass_n.py` *(new)*

### Control plane

- `apps/control-plane/app/review/page.tsx` — `searchParams` → `/api/proposals?…` and **Queue filters** form (`method="get"`, `action="/review"`).

### Proxy

- `apps/control-plane/app/api/proposals/route.ts` — unchanged; already forwards query string to the orchestrator.

## Filters added (query params)

| Param | Behavior |
| --- | --- |
| `review_action_state` | One of `ready_for_review`, `ready_to_publish`, `published`, `not_actionable`. Blank/whitespace ignored. Invalid value → **400**. |
| `staging_status` | Passed to `list_staging_snapshots(status=…)` when non-blank. |
| `has_publication` | `true` / `false` (also `1`/`0`, `yes`/`no`) — filter by `linked_publication_count > 0` or `== 0`. Unrecognized values ignored (no filter). |
| `identity_id` | UUID filter (existing); invalid UUID → **400**. |
| `limit` | `1…200` (existing default **20**). |
| `sort` | `default` (empty) — Pass J tier order, newest `created_at` within tier; `newest` / `oldest` — flat by `created_at` only. Unknown → treated as `default`. |

## Default ordering behavior

- **`sort` omitted or `default`:** Same as Pass J — tier order `ready_for_review` → `ready_to_publish` → `published` → `not_actionable`, then **newest `created_at` first** within each tier (`review_action_sort_key`).
- **`sort=newest`:** Global descending `created_at` (tie-break `staging_snapshot_id`).
- **`sort=oldest`:** Global ascending `created_at`.

When **`review_action_state`**, **`has_publication`**, or **non-default `sort`** is used, the handler requests a **wider pool** from the repository (up to **500** rows, newest `created_at` first), then filters/sorts and applies **`limit`**. Narrow path (no derived filters, default sort): fetch size equals **`limit`** (capped at 500), preserving prior behavior for the default queue view.

## Manual verification checklist

1. Open `/review` with no query string — list loads; default tier ordering; **Pass M** audit hints and action badges still appear on cards.
2. Filter **review_action_state** = `ready_for_review` — only matching cards; URL shows param.
3. **has_publication** = yes / no — results match stored publication links.
4. **sort** = newest / oldest — order follows `created_at` globally.
5. Invalid **review_action_state** — API returns 400; control plane shows error panel if proxied.
6. **Clear filters** link resets to `/review`.
7. `npm run build` in `apps/control-plane` succeeds; `pytest tests/test_proposals_queue_pass_n.py` passes.

## Known limitations

- Wide pool is capped at **500** staging rows (repository limit); very large databases may require future server-side indexed filters.
- **`staging_status`** is a free-form column in the schema; the UI only lists common values (`review_ready`, `approved`).
- **Bulk review actions** are out of scope (same as Pass J).

## Pass F

Publication creation and duplicate-publication prevention are **unchanged**.
