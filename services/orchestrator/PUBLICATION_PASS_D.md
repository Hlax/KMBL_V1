# Human Approval + Publication Promotion (Pass D)

Pass D builds on **Pass A–C**. It adds **explicit operator approval** (`review_ready` → `approved`), **immutable `publication_snapshot` rows** (canon), **read APIs** for publications, and **timeline events** — without habitat evolution, auto-publish, or a workflow engine.

## Principles preserved

- KMBL orchestrates; staging and publication are **persisted** review/canon surfaces.
- **Publication is explicit** (approve, then publish); no auto-promotion.
- Control-plane routes **proxy** the orchestrator; **no** reconstruction from runtime or checkpoints.

---

## Endpoints (orchestrator)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/orchestrator/staging/{staging_snapshot_id}/approve` | `review_ready` → `approved` (idempotent if already `approved`). |
| POST | `/orchestrator/publication` | Create `publication_snapshot` from an **approved** staging row. |
| GET | `/orchestrator/publication` | List publications (newest `published_at` first). |
| GET | `/orchestrator/publication/current` | Latest publication; optional `identity_id`. **404** if none. |
| GET | `/orchestrator/publication/{publication_snapshot_id}` | Full persisted publication row. **404** if missing. |

### Approval rules

- **Allowed:** current status is `review_ready` → set `approved`.
- **Idempotent:** if already `approved`, **200** with current row.
- **Rejected:** other statuses → **409** with `error_kind: approve_ineligible`.
- Optional body: `{ "approved_by": "..." }` (timeline/audit only).

### Publication rules

- Staging row must exist.
- **`validate_publication_eligibility`:** status must be **`approved`**, `review_readiness.approved` must be true, and `snapshot_payload_json` must be a non-empty v1-shaped dict (e.g. `version == 1` or `evaluation` present).
- **Not allowed:** `review_ready` without approval, missing row, or invalid payload → **409** `publication_ineligible`.
- **Payload:** `payload_json` on the publication is a **deep copy** of `staging_snapshot.snapshot_payload_json` at publish time (staging row is **not** mutated for publication content).

### Parent publication

- `parent_publication_snapshot_id` is set to the **latest existing publication for the same `identity_id`**, if any; otherwise `null`.

---

## Response models (stable shapes)

- **`ApproveStagingResponse`:** `staging_snapshot_id`, `thread_id`, `status`, `created_at`, `preview_url`, `review_readiness`.
- **`CreatePublicationResponse`:** `publication_snapshot_id`, `source_staging_snapshot_id`, `identity_id`, `visibility`, `published_at`, `status: "published"`.
- **`PublicationListResponse`:** `publications[]` (`PublicationSnapshotListItem`), `count`.
- **`PublicationSnapshotDetailResponse`:** ids, `payload_json`, `visibility`, `published_by`, `parent_publication_snapshot_id`, `published_at`, etc.

---

## Control-plane proxies

| Product | Upstream |
|---------|----------|
| `POST /api/staging/[id]/approve` | `POST /orchestrator/staging/{id}/approve` |
| `POST /api/publication` | `POST /orchestrator/publication` |
| `GET /api/publication` | `GET /orchestrator/publication` |
| `GET /api/publication/current` | `GET /orchestrator/publication/current` |
| `GET /api/publication/[publicationSnapshotId]` | `GET /orchestrator/publication/{id}` |

Env: `NEXT_PUBLIC_ORCHESTRATOR_URL` (no trailing slash). Status codes and JSON bodies pass through (including **404** / **409**).

---

## Timeline / audit (`graph_run_event`)

When `staging.graph_run_id` is set:

- **`staging_snapshot_approved`:** `staging_snapshot_id`, `thread_id`, `graph_run_id`, `approved_by`.
- **`publication_snapshot_created`:** `publication_snapshot_id`, `source_staging_snapshot_id`, `identity_id`, `visibility`, `published_by`.

If `graph_run_id` is null, events are skipped (edge case).

---

## Persistence

- **Migration:** `supabase/migrations/20260329200000_publication_snapshot.sql` — `publication_snapshot` table.
- **Repository:** `save_publication_snapshot`, `get_publication_snapshot`, `list_publication_snapshots`, `get_latest_publication_snapshot`, `update_staging_snapshot_status` — **InMemory** + **Supabase**.

---

## Read model tweak (Pass C compatibility)

- `review_readiness` on staging now includes **`approved`: bool** (`status == "approved"`).

---

## Local test commands

```bash
cd services/orchestrator
python -m pytest tests/test_publication_pass_d.py tests/test_review_layer_pass_c.py -q
python -m pytest tests/ -q
```

---

## Manual verification checklist

- [ ] Approve a `review_ready` staging row; status becomes `approved`; repeat approve returns **200** without error.
- [ ] POST publication with **unapproved** staging → **409** `staging_not_approved`.
- [ ] POST publication after approve → **200**; GET publication detail matches persisted `payload_json`.
- [ ] GET `/orchestrator/publication/current` with no rows → **404**.
- [ ] Control-plane POST/GET proxy returns same status codes as orchestrator.

---

## Known limitations

- No reviewer assignment, comments, scheduling, or multi-step workflows.
- No automatic promotion of “latest” staging.
- Timeline events require `graph_run_id` on the staging row.
- Control-plane proxy tests are manual (no Jest/Vitest in app workspace).

---

## Success criteria

- Operators can **approve** then **publish** in two explicit steps.
- **Publication snapshots are immutable** and listed/read by id; **current** convenience read is available.
- **Canon** is only created via **POST /orchestrator/publication** after **approval**.
