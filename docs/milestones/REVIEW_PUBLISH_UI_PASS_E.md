# Pass E: Control-Plane Review + Approve + Publish Flow

This pass wires the existing orchestrator-backed API routes into minimal operator pages in the Next.js control plane. All reads go through the control-plane `/api/*` proxies to the Python orchestrator; mutations revalidate via `router.refresh()` (no optimistic local state as source of truth).

## Routes and files

| Route | Purpose |
| --- | --- |
| `/` | Home — links to Review, Publication, and Status (debug) |
| `/review` | Review list — `GET /api/proposals` |
| `/review/staging/[stagingSnapshotId]` | Staging detail — `GET /api/staging/[id]`; Approve — `POST /api/staging/[id]/approve`; Publish — `POST /api/publication` |
| `/publication` | Current latest + list — `GET /api/publication/current`, `GET /api/publication` |
| `/publication/[publicationSnapshotId]` | Canon detail — `GET /api/publication/[id]` |
| `/status` | Unchanged: orchestrator health / graph run debug (not the operator canon flow) |

### Added or changed (control plane)

- `app/components/ControlPlaneNav.tsx` — global nav (Home, Review, Publication, Status).
- `app/layout.tsx` — includes `ControlPlaneNav`.
- `app/page.tsx` — operator-flow links.
- `app/globals.css` — minimal operator styling (banners, cards, buttons, preview frame).
- `app/review/page.tsx` — proposal cards from persisted proposals.
- `app/review/staging/[stagingSnapshotId]/page.tsx` — staging review surface + iframe preview when URL is http(s).
- `app/review/staging/[stagingSnapshotId]/StagingReviewActions.tsx` — client: approve + publish forms.
- `app/review/staging/[stagingSnapshotId]/not-found.tsx` — 404 copy.
- `app/publication/page.tsx` — current + list.
- `app/publication/[publicationSnapshotId]/page.tsx` — publication detail.
- `app/publication/[publicationSnapshotId]/not-found.tsx` — 404 copy.
- `lib/server-origin.ts` — same-origin base URL for server components calling `/api/*`.
- `lib/api-types.ts` — loose TypeScript shapes for JSON responses.

### APIs consumed (via control-plane)

| UI | Method | Path |
| --- | --- | --- |
| Review list | GET | `/api/proposals` |
| Staging detail | GET | `/api/staging/[stagingSnapshotId]` |
| Approve | POST | `/api/staging/[stagingSnapshotId]/approve` — body `{ approved_by?: string }` |
| Publish | POST | `/api/publication` — body `{ staging_snapshot_id, visibility, published_by? }` |
| Publication list | GET | `/api/publication` |
| Current publication | GET | `/api/publication/current` |
| Publication detail | GET | `/api/publication/[publicationSnapshotId]` |

## Mutation flow

1. **Approve** (staging only): shown when persisted `status === "review_ready"`. On success, `router.refresh()` reloads the staging page from the server so `status` and `review_readiness` reflect persisted truth. HTTP **409** shows the orchestrator error payload (e.g. not in `review_ready`).
2. **Publish** (canon): shown when persisted `status === "approved"`. On success, response may include `publication_snapshot_id`; a link to `/publication/[id]` is shown when parsed. `router.refresh()` updates the staging page (staging row remains **approved**; publication is a separate immutable row).

No combined “approve and publish” control; no auto-publish.

## Local run

Prerequisites: orchestrator running and reachable, and `NEXT_PUBLIC_ORCHESTRATOR_URL` set for the control plane (see repo `.env.example` / `apps/control-plane/.env.example`).

From the monorepo root:

```bash
cd apps/control-plane
npm install
npm run dev
```

Open `http://localhost:3000`, use **Review** and **Publication** in the nav.

Server components resolve the app origin from request headers (`x-forwarded-host` / `host`) when calling `/api/*` from the server.

## Manual verification checklist

- [ ] **Review list**: `/review` loads; when the orchestrator returns proposals, cards show title, evaluation summary, preview availability, created time, identity hint (if present), staging status / review readiness; each card links to `/review/staging/...`.
- [ ] **Empty proposals**: With no `review_ready` rows, the list shows a clear empty state (not fake data).
- [ ] **Staging detail**: Opening a card loads persisted fields (title/summary, evaluation, preview URL, `review_readiness`, `status`, `payload_version`, payload hints). Raw JSON is under an expandable **Raw JSON (debug)** section.
- [ ] **Preview**: If `preview_url` is `http`/`https`, an embedded iframe appears plus an external link; unsafe schemes are not embedded.
- [ ] **Approve**: For `review_ready` rows, Approve calls the API; on **200**, the page refreshes and shows `approved` / publish section; on **409**, an error message is shown without faking status locally.
- [ ] **Publish**: For `approved` rows, Publish submits visibility + optional `published_by`; on **200**, `publication_snapshot_id` is surfaced when present and links to publication detail; **409** (e.g. not approved) shows cleanly.
- [ ] **Publication index**: `/publication` shows current latest (or “none” when `/api/publication/current` is 404) and a list from `GET /api/publication`.
- [ ] **Publication detail**: `/publication/[id]` shows metadata and structured payload; raw payload in `<details>`.
- [ ] **404**: Unknown staging or publication id shows the route `not-found` pages.
- [ ] **Orchestrator down / misconfig**: Error panels when `/api/*` returns errors (e.g. 500 / 502), without silent success.

## Known limitations

- **Server-side fetch origin**: Relies on correct `Host` / `x-forwarded-*` headers when the control plane is behind a reverse proxy; if same-origin server fetch fails in an unusual deployment, set a documented explicit public origin (not introduced in this pass).
- **Duplicate publish**: The UI does not hide Publish after a successful publication from the same staging row; the orchestrator may allow multiple publications unless constrained server-side.
- **No notifications / toasts**: Success and errors are inline text only.
- **iframe previews**: Some sites block embedding (`X-Frame-Options`); the external link remains the reliable path.

## Orchestrator / API changes

None required for this pass; existing Pass A–D routes are sufficient.
