# Pass F: Publication constraints, auditability, lifecycle timeline

Builds on Pass E (control-plane review / approve / publish) with orchestrator-backed rules and read models.

## What changed

### Orchestrator

- **Duplicate publication policy**: `POST /orchestrator/publication` returns **409** with `error_kind: "publication_already_exists_for_staging"` if any `publication_snapshot` row already exists for the same `source_staging_snapshot_id`. Response includes `publication_snapshot_id` of the existing row (newest first in repo).
- **Staging approval audit**: `staging_snapshot` gains `approved_by` and `approved_at` (Supabase migration). `POST .../approve` sets them when transitioning to `approved`. `ApproveStagingResponse` includes `approved_by` and `approved_at`. Idempotent approve returns the persisted audit fields.
- **Staging detail enrichment**: `GET /orchestrator/staging/{id}` returns:
  - `approved_by`, `approved_at`
  - `linked_publications` — newest first
  - `lifecycle_timeline` — derived list from persisted staging + linked publications only
- **Create publication response**: `published_by` included in `CreatePublicationResponse`.

### Repository

- `update_staging_snapshot_status(..., approved_by=...)` — audit fields when status is `approved`.
- `list_publications_for_staging(staging_snapshot_id)` — all publications for that staging id, newest `published_at` first.

### Control plane

- `lib/api-types.ts` — types for `linked_publications`, `lifecycle_timeline`, staging audit fields.
- Staging detail page — linked publications panel, lifecycle timeline, audit rows in summary; `StagingReviewActions` receives `linkedPublicationCount`; publish form hidden when a linked publication exists (server still enforces).
- Error parsing for `publish`/`approve` **409** bodies (including `error_kind` + `message`).
- Publication detail — audit fields (`published_at` formatted, `published_by`) emphasized; copy tightened.
- Review + publication index — wording aligned (staging vs canon vs runtime).

## Routes / APIs affected

| Area | Change |
| --- | --- |
| `GET /api/staging/[id]` | Proxies richer orchestrator JSON (timeline, linked pubs, audit). |
| `POST /api/staging/[id]/approve` | Same path; orchestrator persists audit fields. |
| `POST /api/publication` | May return 409 duplicate staging. |

## Publication duplication rule

- **One publication per staging snapshot** (Pass F): second publish for the same `staging_snapshot_id` is **409** with `publication_already_exists_for_staging`.
- Future “allow multiple” would require an explicit policy flag and schema change.

## Audit fields surfaced

| Field | Where |
| --- | --- |
| `approved_by`, `approved_at` | Staging detail summary; approve API response |
| `published_by`, `published_at` | Publication detail; linked publication cards on staging; create publication response |

## Lifecycle timeline behavior

- Built in `staging_lifecycle_timeline()` from **persisted** `StagingSnapshotRecord` + `list_publications_for_staging` only.
- **Omitted** when a timestamp cannot be proven (e.g. approval line omitted if `approved_at` is missing — legacy rows before migration).
- Events include: staging persisted, review-ready (when applicable), approval (when `approved_at` set), each publication with link id.

## Manual verification checklist

- [ ] Run Supabase migration `20260329210000_staging_snapshot_approval_audit.sql` on your DB.
- [ ] Approve a `review_ready` staging row; `approved_at` / `approved_by` appear on staging detail and in approve JSON.
- [ ] Publish once; second publish for same staging id returns **409** with `publication_already_exists_for_staging`; UI shows inline message if triggered.
- [ ] Staging detail shows linked publication(s) and lifecycle list; publication links work.
- [ ] Publication detail shows `published_at` (formatted) and `published_by`.
- [ ] Control plane: `npm run build` succeeds.

## Known limitations

- **Legacy staging rows**: Approved before Pass F may lack `approved_at`; the “approved” timeline step is omitted.
- **Review-ready vs created**: Both may share `created_at` when the row is created as `review_ready` — intentional.
- **Duplicate policy**: Deliberately conservative; relaxing requires product + schema decision.
