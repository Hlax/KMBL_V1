# Pass P: Identity-aware navigation and filtering

Modest **navigation-focused** improvements: consistent optional `identity_id` (UUID) filtering on index pages, clearer copy, and **clickable `identity_id`** on detail surfaces that link into the right filtered list. No dedicated `/identity/[id]` page. No new mutation endpoints. No streaming.

## Files changed

| Area | Path |
|------|------|
| Identity link helpers | `apps/control-plane/lib/identity-nav.ts` |
| Home | `apps/control-plane/app/page.tsx` |
| Runs index | `apps/control-plane/app/runs/page.tsx` |
| Run detail | `apps/control-plane/app/runs/[graphRunId]/page.tsx` |
| Review index | `apps/control-plane/app/review/page.tsx` |
| Staging detail | `apps/control-plane/app/review/staging/[stagingSnapshotId]/page.tsx` |
| Publication index | `apps/control-plane/app/publication/page.tsx` |
| Publication detail | `apps/control-plane/app/publication/[publicationSnapshotId]/page.tsx` |

**Orchestrator / API:** unchanged for Pass P. `GET /orchestrator/publication` and `GET /orchestrator/publication/current` already accept `identity_id`; the control-plane `/api/publication` and `/api/publication/current` routes already forward query strings.

## Identity filter behavior by page

All filters use **GET forms** (`method="get"`), so the browser sets query params on the page URL. **Blank or whitespace-only** `identity_id` should be omitted from requests (operators clear the field or use “Clear filters”); the orchestrator treats empty `identity_id` as “no filter” where applicable. **Non-blank** values must be valid UUIDs: the orchestrator validates and returns **400** with `invalid identity_id` when malformed.

| Page | Query params | Backend |
|------|----------------|---------|
| `/runs` | `identity_id`, `status`, `trigger_type`, `limit` | `GET /api/runs` → `GET /orchestrator/runs` |
| `/review` | `identity_id`, `review_action_state`, `staging_status`, `has_publication`, `sort`, `limit` | `GET /api/proposals` → `GET /orchestrator/proposals` |
| `/publication` | `identity_id`, `visibility`, `limit` | `GET /api/publication` → `GET /orchestrator/publication`; **Current** block uses `GET /api/publication/current` with the same `identity_id` when set |

**Publication index (new vs before):** Optional `identity_id` filter is exposed in the UI. The **Recent publications** list and the **Current (latest)** card both respect the filter: when `identity_id` is set, “current” means latest publication **for that identity** (or 404 copy explaining none for that identity).

## Linking behavior from detail pages

| Detail | Field | Target |
|--------|--------|--------|
| Run (`/runs/[graphRunId]`) | `summary.identity_id` | `/runs?identity_id=…` |
| Staging (`/review/staging/[id]`) | `lineage.identity_id` | `/review?identity_id=…` |
| Publication (`/publication/[id]`) | lineage `identity_id` | `/publication?identity_id=…` |

**Review queue cards:** When a proposal row includes `identity_id`, the identity line links to `/review?identity_id=…` (hint or full id as label).

**Runs table:** New **identity_id** column; when present, the cell links to `/runs?identity_id=…`.

## Pass F

**Duplicate-publication behavior is unchanged.** `POST /orchestrator/publication` still returns **409** when a publication already exists for the same staging snapshot. Pass P only touches read paths and UI.

## Manual verification checklist

1. **Runs:** Open `/runs`, enter a valid `identity_id` in the filter, Apply — URL contains `identity_id`, table shows filtered rows; clear via “Clear filters”.
2. **Runs:** Submit an invalid `identity_id` (e.g. `not-a-uuid`) — expect error panel from API (400).
3. **Runs:** Open a run with `identity_id` set — value is a link; click → `/runs?identity_id=…`.
4. **Review:** Same valid/invalid checks for `/review?identity_id=…`.
5. **Review:** From a staging detail with `lineage.identity_id`, click — lands on `/review?identity_id=…`.
6. **Publication:** `/publication` — filter by `identity_id`, Apply — list and “Current” reflect identity scope; invalid UUID → error.
7. **Publication:** From publication detail, click `identity_id` — `/publication?identity_id=…`.
8. **Home:** Copy mentions identity filters on Runs / Review / Publication (no new routes).
9. **Regression:** Publish flow and second publish to same staging still **409** (Pass F).

## Known limitations

- **Exact UUID only** — no search, fuzzy match, or human-readable identity directory.
- **No `/identity/[id]` hub** — cross-surface navigation is via filtered index pages only.
- **Depends on persisted data** — rows without `identity_id` show “—” where applicable.
- **Server truth** — filters mirror orchestrator/repository semantics; empty filter means global list (publication “current” = latest overall when no `identity_id`).

## Exact test steps (local)

1. From repo root: `cd apps/control-plane && npm run build` — expect success (already run in Pass P).
2. With orchestrator up and `NEXT_PUBLIC_ORCHESTRATOR_URL` set, start `npm run dev`, visit `/runs`, `/review`, `/publication` and exercise filters and links above.

## Repository / schema assumptions

- **Identity** is a UUID carried on `thread`, staging, publication, and derived run list read models, consistent with existing migrations and orchestrator models.
- **Publication list** items include `identity_id` when present (`PublicationSnapshotListItem`), so the publication index can show and link per row.
