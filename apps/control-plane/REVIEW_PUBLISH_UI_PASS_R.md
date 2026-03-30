# Pass R: Cross-surface context navigation polish

UI-only pass: consistent **small-link labels** (`overview`, `runs`, `queue`, `list`), clearer **identity overview** section copy, **direct detail** affordances (`title` on overview links), and **return-path** breadcrumbs on detail pages when `identity_id` is known. No new APIs, no mutations, no streaming. **Pass F** duplicate-publication behavior unchanged.

## Files changed

| File | Change |
|------|--------|
| `apps/control-plane/app/components/IdentityNavExtras.tsx` | **New** — `IdentityNavExtras` (overview · runs · queue · list) and `IdentityContextLinks` (runs · queue · list for UUID rows) |
| `apps/control-plane/app/identity/[identityId]/page.tsx` | Summary wording (`queue` / `list`); section intros (`Preview` + `runs` / `queue` / `list`); `title` on run / staging / publication detail links |
| `apps/control-plane/app/runs/page.tsx` | Identity column secondary link text `(list)` → **`runs`** |
| `apps/control-plane/app/runs/[graphRunId]/page.tsx` | Top nav: **Publication** + `IdentityNavExtras` when `identity_id` present; identity row uses **`IdentityContextLinks`** |
| `apps/control-plane/app/review/page.tsx` | Proposal cards: **`IdentityContextLinks`** after identity hint |
| `apps/control-plane/app/review/staging/[stagingSnapshotId]/page.tsx` | Breadcrumb: `IdentityNavExtras` when identity known; lineage **`IdentityContextLinks`** |
| `apps/control-plane/app/publication/page.tsx` | Identity rows: **`IdentityContextLinks`** after overview UUID |
| `apps/control-plane/app/publication/[publicationSnapshotId]/page.tsx` | Breadcrumb: **`IdentityNavExtras`**; lineage **`IdentityContextLinks`** |

## Navigation / linking improvements

### Standardized labels

- **`overview`** — `/identity/[uuid]` (also the primary UUID link target in lineage rows).
- **`runs`** — `/runs?identity_id=…`
- **`queue`** — `/review?identity_id=…`
- **`list`** — `/publication?identity_id=…`

Parentheses and synonyms such as `(list)`, `(queue)`, “Publication index (filtered)”, “Full queue for this identity” were removed in favor of these words.

### Identity overview (`/identity/[identityId]`)

- Section summaries use **Preview (up to N). Full index: `runs` / `queue` / `list`** (links).
- Summary paragraph uses **`queue`** and **`list`** instead of “review” / “publication” for the filtered indexes.
- Run / staging / publication preview titles keep **direct hrefs** to detail routes; **`title`** attributes clarify **Run detail**, **Staging detail**, **Publication detail**.

### Detail breadcrumbs

When identity is available:

- **Run detail** — `← Runs · Review · Publication · overview · runs · queue · list`
- **Staging detail** — `← Review list · overview · runs · queue · list` (from `identity_id` or lineage)
- **Publication detail** — `← Publication index · overview · runs · queue · list`

### Identity rows (UUID + shortcuts)

Where the main link is the UUID → overview, the secondary strip is **`runs · queue · list`** via **`IdentityContextLinks`** (no duplicate “overview” word).

## Manual verification checklist

1. **`/identity/{uuid}`** — Runtime / Review / Canon sections show **runs** / **queue** / **list** index links; preview rows link to **run**, **staging**, **publication** detail URLs; hover shows **title** tooltips where added.
2. **Run detail** (with `identity_id`) — Top line includes **Publication** and the four identity links; identity row shows UUID + **runs · queue · list**.
3. **Staging detail** — Breadcrumb extras when identity present; lineage **identity_id** matches pattern.
4. **Publication detail** — Breadcrumb extras; lineage **identity_id** matches pattern.
5. **Review list** — Proposal cards with identity show **runs · queue · list** after the hint link.
6. **Runs index** — Identity column secondary link reads **`runs`** (filtered list).
7. **`npm run build`** in `apps/control-plane` — succeeds.

## Known limitations

- **Wide proposal rows** — Cards with `IdentityContextLinks` add three short links; may wrap on narrow viewports (acceptable tradeoff for consistency).
- **Identity on staging breadcrumb** — Uses `data.identity_id` or `lineage.identity_id` only; if both missing, no extras (unchanged data model).

## Exact test steps

```bash
cd apps/control-plane
npm run build
```

Then manually spot-check URLs above with a run/staging/publication row that includes an `identity_id`.

## Repository / schema assumptions

Unchanged: identity is the persisted UUID already carried on rows; no schema or orchestrator changes.
