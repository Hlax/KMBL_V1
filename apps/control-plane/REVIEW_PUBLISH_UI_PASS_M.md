# Pass M: Review / publication audit visibility

Lightweight **persisted** operator-action visibility on staging review and canon publication surfaces, in the same spirit as Pass L for runtime. All UI copy is derived from **stored staging and publication rows** — no new mutations, no live streaming.

## Files changed

### Orchestrator

- `services/orchestrator/src/kmbl_orchestrator/staging/read_model.py` — `proposal_read_model` now includes `approved_at` and `approved_by` from the staging row (for `/orchestrator/proposals`).

### Control plane

- `apps/control-plane/lib/review-publication-audit-read-model.ts` — shared helpers: `buildStagingOperatorActions`, `buildProposalAuditHints`, `buildPublicationAuditFacts`.
- `apps/control-plane/lib/api-types.ts` — `ProposalRow` optional `approved_at`, `approved_by`.
- `apps/control-plane/app/review/staging/[stagingSnapshotId]/page.tsx` — **Operator actions (persisted)** section.
- `apps/control-plane/app/publication/[publicationSnapshotId]/page.tsx` — tightened **Audit (persisted)** block + slimmer **Lineage (ids)** (graph run links to `/runs/[id]`).
- `apps/control-plane/app/review/page.tsx` — subtle audit hints on proposal cards.
- `apps/control-plane/app/globals.css` — `.op-audit-history*`, `.op-proposal-audit-hint`.

### Tests

- `services/orchestrator/tests/test_staging_audit_pass_m.py`

## Audit derivation rules

### Staging detail — operator actions

- **Approved:** only if `approved_at` is present on the staging row; actor from `approved_by` when set.
- **Published:** one entry per row in `linked_publications` (orchestrator-sourced), with `published_at`, `published_by`, and link to `/publication/[id]`.
- Items are sorted by timestamp ascending. **No** synthetic events when data is missing (e.g. no `approved_at` → no approved row).

### Review list — card hints

- From `proposal_read_model` + existing `linked_publication_count` and `staging_status` (already on proposals):
  - **Approved by X** when `approved_by` is set.
  - **approved on {date}** when `approved_at` is set.
  - **Already published** when `linked_publication_count > 0`.
  - **Awaiting publication** when status is `approved` and publication count is 0.

### Publication detail — audit block

- **Published to canon:** `published_at`, `published_by` (or “actor not recorded”).
- **Identifiers:** `publication_snapshot_id`, `visibility`.
- **Provenance:** `source_staging_snapshot_id` and `parent_publication_snapshot_id` as links when present (`publication_lineage` or top-level fields).

## UI behavior

- Staging: new panel sits **after** Summary and **before** Lifecycle timeline; empty state when there are no approval/publication actions.
- Review: one muted line under the action badge when any hint applies.
- Publication: audit reads as a short **action history** (ordered list with one primary step) plus a definition list for ids and links.

## Manual verification checklist

1. **Staging** with approved staging + at least one linked publication: operator section shows approve + publish lines with links to publication detail.
2. **Staging** with no approval and no publications: operator section shows empty state; lifecycle may still show “staging persisted”.
3. **Review list:** approved rows show “Approved by …” / “approved on …”; approved without publication shows “Awaiting publication”; rows with publications show “Already published”.
4. **Publication detail:** audit shows published time, actor, staging link, parent link; lineage shows thread/graph run/identity; graph run links to run detail.
5. `npm run build` (control plane) succeeds; `pytest` includes `test_staging_audit_pass_m.py`.

## Known limitations

- **Proposals API** only gained `approved_*` fields; publication timestamps on the list are **not** duplicated (use detail or staging for exact publish time).
- **Multiple publications** per staging (if policy allows) render as multiple published lines in operator actions.
- **Rejection workflow** is out of scope unless already modeled on the row (not added here).

## Pass F

Duplicate-publication prevention and publication APIs are **unchanged**; this pass is read-model + UI only.
