# Review / Proposal Layer (Pass C — Minimal, Real)

Pass C sits on **Runtime Hardening (Pass A)**, **Staging / Output Integrity (Pass B)**, and **Pass B.5** refinements. It adds:

- A **queryable list** of persisted `staging_snapshot` rows (newest first, filters, no full payload blobs).
- A **thin proposal read model** derived only from persisted rows — **not** a workflow or approval state machine.
- **Stable staging detail** aligned to DB truth (`GET /orchestrator/staging/{id}`) with an explicit response model.
- **Control-plane read proxies** so the UI reads orchestrator persisted truth only (no local reconstruction).

**Out of scope:** approval transitions, publish mutations, habitat evolution, UI redesign, queue/job changes, orchestrator execution redesign.

---

## Endpoints added / changed

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/orchestrator/staging` | Paginated list of persisted snapshots (lightweight rows). |
| GET | `/orchestrator/proposals` | Review-ready proposals only (derived read model). |
| GET | `/orchestrator/staging/{staging_snapshot_id}` | Single persisted snapshot + derived fields (`StagingSnapshotDetailResponse`). |

### Query parameters

**`GET /orchestrator/staging`**

- `limit` — default **20**, max **200**
- `status` — optional, exact match on `staging_snapshot.status`
- `identity_id` — optional UUID filter

**`GET /orchestrator/proposals`**

- `limit` — default **20**, max **200**
- `identity_id` — optional UUID filter (same semantics as list)

Ordering for both list operations: **`created_at` descending** (newest first), implemented in `Repository.list_staging_snapshots` (in-memory + Supabase).

---

## Proposal derivation rules

Proposals are a **read model** computed in endpoint/service code — **no new table**.

1. **Source:** persisted `staging_snapshot` rows with `status == "review_ready"` (same signal as `review_readiness.ready` in the payload-derived helper).
2. **`proposal_id`** currently equals **`staging_snapshot_id`**.
3. **Excluded:** any row not in `review_ready` (e.g. hypothetical `archived` or blocked statuses).
4. **No** raw provider blobs: titles and evaluation text come from **`snapshot_payload_json`** (v1 shape) only.

---

## Response shapes

### `GET /orchestrator/staging`

```json
{
  "snapshots": [ /* lightweight rows */ ],
  "count": 0
}
```

Each **`snapshots[]`** item (no full `snapshot_payload_json`):

| Field | Description |
|-------|-------------|
| `staging_snapshot_id` | UUID string |
| `thread_id` | UUID string |
| `identity_id` | UUID string or null |
| `created_at` | ISO timestamp from row |
| `status` | Row status |
| `preview_url` | From row |
| `review_readiness` | `{ ready, basis, staging_status }` |
| `evaluation_summary` | From `snapshot_payload_json.evaluation.summary` (v1) |
| `title` | Card title: `summary.title`, else optional `build_spec.title`, else safe fallback label |
| `payload_version` | From `snapshot_payload_json.version` when an int (e.g. `1`) |
| `identity_hint` | Optional short hint when `identity_id` is set |

### `GET /orchestrator/proposals`

```json
{
  "proposals": [ /* review-ready only */ ],
  "count": 0
}
```

Each **`proposals[]`** item:

| Field | Description |
|-------|-------------|
| `proposal_id` | Same as `staging_snapshot_id` for now |
| `staging_snapshot_id` | UUID string |
| `thread_id`, `identity_id`, `created_at`, `preview_url` | From row |
| `title`, `summary` | Both set to the same compact title string for list/review surfaces |
| `evaluation_summary` | From persisted payload |
| `review_readiness` | Same helper as list |
| `staging_status` | Row `status` (echo for clarity) |

### `GET /orchestrator/staging/{id}` — `StagingSnapshotDetailResponse`

Persisted fields plus derived:

- `snapshot_payload_json` — full v1 payload (ids, summary, evaluation, preview, artifacts, metadata).
- `evaluation_summary`, `short_title`, `identity_hint`, `review_readiness`, `payload_version`.
- **404** if the row does not exist; **400** for invalid UUID.

---

## Control-plane proxies

| Product route | Upstream |
|---------------|----------|
| `GET /api/staging` | `GET /orchestrator/staging` (query string forwarded) |
| `GET /api/staging/[stagingSnapshotId]` | `GET /orchestrator/staging/{id}` |
| `GET /api/proposals` | `GET /orchestrator/proposals` |

Environment: `NEXT_PUBLIC_ORCHESTRATOR_URL` (no trailing slash). Status codes and JSON bodies are passed through (including **404** on missing staging id).

---

## Timeline bridge (review ↔ runtime)

`staging_snapshot_created` append-only events include:

- `staging_snapshot_id`
- `graph_run_id`, `thread_id` — link run status views to review objects
- `preview_url` when present
- `review_ready: true`
- `build_candidate_id`, `reason`

---

## Code modules

- `src/kmbl_orchestrator/staging/read_model.py` — list rows, proposals, title/version extractors.
- `src/kmbl_orchestrator/api/main.py` — routes + `StagingSnapshotDetailResponse`.
- `src/kmbl_orchestrator/persistence/repository.py` / `supabase_repository.py` — `list_staging_snapshots`.
- `apps/control-plane/app/api/staging/route.ts`, `[stagingSnapshotId]/route.ts`, `proposals/route.ts`.

---

## Local test commands

```bash
cd services/orchestrator
python -m pytest tests/test_review_layer_pass_c.py tests/test_staging_pass_b.py -q
python -m pytest tests/ -q
```

---

## Manual verification checklist

- [ ] `GET /orchestrator/staging` returns `snapshots` without embedded full `snapshot_payload_json`.
- [ ] `GET /orchestrator/proposals` returns only `review_ready` rows; count matches expectations.
- [ ] `GET /orchestrator/staging/{uuid}` returns **404** for unknown id.
- [ ] With `NEXT_PUBLIC_ORCHESTRATOR_URL` set, `GET /api/staging`, `/api/proposals`, and `/api/staging/{id}` mirror orchestrator status and JSON.
- [ ] After a stub graph run, timeline includes `staging_snapshot_created` with `preview_url`, `review_ready`, `graph_run_id`, `thread_id`.

---

## Known remaining limitations

- **No approval workflow**, publication API, reviewer assignment, or comments.
- **Proposals** are not a separate durable entity — only a filtered/derived view of `staging_snapshot`.
- **List** does not join tables beyond the snapshot row; all summary text comes from persisted `snapshot_payload_json`.
- **Control-plane** proxy tests are not automated in this repo (Next.js app has no test runner wired); verify via manual calls or future E2E.

---

## Success criteria (Pass C)

- Operators can **list** persisted staging snapshots.
- Operators can **list** review-ready proposals (`GET /orchestrator/proposals`).
- Operators can **fetch** persisted staging detail with a stable shape.
- Control-plane **read** routes align to orchestrator persisted truth.
- System is ready for a **next pass**: human approval / publish — without introducing workflow state in Pass C.
