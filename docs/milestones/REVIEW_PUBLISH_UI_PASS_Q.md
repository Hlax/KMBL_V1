# Pass Q: Lightweight identity overview

Adds a **modest** server-rendered **`/identity/[identityId]`** page that composes existing persisted read APIs into one place. No new orchestrator endpoints, no mutations, no streaming. **Pass F** duplicate-publication rules are unchanged (publish path untouched).

## Files changed

| File | Role |
|------|------|
| `apps/control-plane/lib/identity-nav.ts` | `parseIdentityUuidParam`, `identityOverviewPath`; shared UUID validation for the route |
| `apps/control-plane/app/identity/[identityId]/page.tsx` | **New** — overview UI |
| `apps/control-plane/app/page.tsx` | Home copy mentions `/identity/<uuid>` |
| `apps/control-plane/app/runs/page.tsx` | Identity column: overview + `(list)` |
| `apps/control-plane/app/runs/[graphRunId]/page.tsx` | `identity_id`: overview + `(runs)` / `(review)` / `(publication)` |
| `apps/control-plane/app/review/page.tsx` | Proposal cards: overview + `(queue)` |
| `apps/control-plane/app/review/staging/[stagingSnapshotId]/page.tsx` | Lineage `identity_id`: overview + `(queue)` |
| `apps/control-plane/app/publication/page.tsx` | Current + list `identity_id`: overview + `(list)` |
| `apps/control-plane/app/publication/[publicationSnapshotId]/page.tsx` | Lineage `identity_id`: overview + `(list)` |

## Data sourcing approach

The overview page **only** calls existing control-plane proxies (same as filtered index pages):

| Fetch | Purpose |
|-------|---------|
| `GET /api/runs?identity_id=<uuid>&limit=5` | Recent runs (preview) |
| `GET /api/proposals?identity_id=<uuid>&limit=5` | Recent staging-derived proposals |
| `GET /api/publication?identity_id=<uuid>&limit=5` | Recent publication rows |
| `GET /api/publication/current?identity_id=<uuid>` | Latest publication **for that identity** (404 if none) |

Parallel `fetch` with `cache: "no-store"`. Invalid path UUIDs are **not** sent to the API — the page shows a client-side validation message (canonical 8-4-4-4-12 hex pattern, normalized to lowercase for display and requests).

## Sections shown

1. **Summary** — `identity_id` and short copy; links to filtered runs / review / publication index.
2. **Runtime** — Up to 5 runs with status, trigger, time, attention badge; link to full `/runs?identity_id=…`.
3. **Review queue** — Up to 5 proposals with title + staging id; link to `/review?identity_id=…` and per-row staging detail.
4. **Canon** — “Current” publication for the identity (if any), plus up to 5 recent publication rows; links to detail and filtered publication index.

Per-section errors (e.g. orchestrator down) are isolated so other sections still render when data is available.

## Linking pattern (Pass P + Q)

Where `identity_id` appears on detail/list UIs, the **primary** link targets **`/identity/<uuid>`** (overview). Secondary muted links keep Pass P **filtered index** shortcuts: `(runs)`, `(review)` / `(queue)`, `(publication)` / `(list)` as appropriate.

## Manual verification checklist

1. **`/identity/not-a-uuid`** — Error panel; no orchestrator calls with invalid id (check network or logs).
2. **Valid UUID with no data** — Page loads; sections may show empty copy; current publication may show “none for this identity” when 404 on current.
3. **Valid UUID with data** — Previews populate; links to run detail, staging, publication detail work.
4. **Footer** — Shareable path shows `/identity/<uuid>`.
5. **From run detail** — `identity_id` row: overview + three filtered links.
6. **`npm run build`** in `apps/control-plane` — succeeds.

## Known limitations

- **Not an identity management system** — no CRUD, no auth, no profile.
- **Bounded previews** — limit 5 per list; full history only via filtered index pages.
- **Independent fetches** — four round-trips; acceptable for a modest overview.
- **UUID path only** — same strict shape as `parseIdentityUuidParam`; exotic UUID formats not accepted.

## Exact test steps

```bash
cd apps/control-plane
npm run build
```

Then with dev server and `NEXT_PUBLIC_ORCHESTRATOR_URL` set, visit `/identity/00000000-0000-0000-0000-000000000001` (or a real id from your DB) and exercise links.

## Repository / schema assumptions

Unchanged from Pass P: `identity_id` is the persisted UUID on threads, staging, publications, and run list read models. No migrations.

## Pass F

No changes to `POST /orchestrator/publication` or duplicate-publication handling.
