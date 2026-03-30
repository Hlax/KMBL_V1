# Pass G: Lineage & evaluation visibility (review surfaces)

Adds structured lineage, persisted evaluation detail, and review-readiness copy on staging; grouped publication lineage on canon detail. Server truth only; no change to Pass F duplicate-publication behavior.

## Files changed

**Orchestrator**

- `src/kmbl_orchestrator/staging/read_model.py` — `staging_lineage_read_model`, `evaluation_summary_section_from_payload`, `review_readiness_explanation_for_staging`
- `src/kmbl_orchestrator/api/main.py` — `StagingLineageSection`, `StagingEvaluationDetail`, `PublicationLineageSection`; `StagingSnapshotDetailResponse.lineage`, `.evaluation`, `.review_readiness_explanation`; `PublicationSnapshotDetailResponse.publication_lineage`; `_publication_detail` and `get_staging_snapshot` wiring

**Tests**

- `tests/test_review_layer_pass_c.py` — staging detail assertions for Pass G fields
- `tests/test_publication_pass_d.py` — `publication_lineage` on publication GET

**Control plane**

- `lib/api-types.ts` — `StagingLineage`, `StagingEvaluationDetail`, `PublicationLineage`, extended `StagingDetail` / `PublicationDetail`
- `app/review/staging/[stagingSnapshotId]/page.tsx` — section order: summary (+ review explanation), lifecycle, lineage, evaluation, linked canon, preview, payload hints (collapsible), actions, raw JSON
- `app/publication/[publicationSnapshotId]/page.tsx` — audit block + lineage block with links to staging and parent publication

## Lineage fields surfaced

### Staging (`GET /orchestrator/staging/{id}` → `lineage`)

| Field | Source |
| --- | --- |
| `thread_id` | Staging row |
| `graph_run_id` | Staging row (nullable) |
| `build_candidate_id` | Staging row |
| `evaluation_report_id` | `snapshot_payload_json.ids.evaluation_report_id` when present |
| `identity_id` | Staging row |

### Publication (`publication_lineage` + existing top-level fields)

| Field | Role |
| --- | --- |
| `source_staging_snapshot_id` | Link target for staging review |
| `parent_publication_snapshot_id` | Link target for prior canon |
| `identity_id`, `thread_id`, `graph_run_id` | same as persisted row |

## Evaluation summary behavior

- `evaluation` object: `present`, `status`, `summary`, `issue_count`, `artifact_count`, `metrics_key_count`, up to **5** `metrics_preview` entries (key → truncated string).
- Sourced only from `snapshot_payload_json.evaluation` / `artifacts` — not live evaluator calls.

## Review readiness explanation

- Short string derived from **persisted** `staging_snapshot.status` and `snapshot_payload_json.evaluation` only.
- Examples: `review_ready` + `pass` → eligible for review; missing evaluation block → not confident; `approved` → may publish once per Pass F policy.

## Manual verification checklist

- [ ] Staging detail shows **Lineage** without opening raw JSON.
- [ ] Staging shows **Evaluation** section when payload has evaluation; metrics preview when metrics present.
- [ ] **Review readiness (explained)** matches orchestrator `review_readiness_explanation`.
- [ ] Publication detail **Lineage** shows links to `/review/staging/[id]` and parent `/publication/[id]` when ids present.
- [ ] `graph_run_id` appears as plain text (no run-detail page required).
- [ ] `npm run build` in `apps/control-plane` succeeds.
- [ ] Second publish same staging still **409** (Pass F unchanged).

## Known limitations

- **Metrics preview** caps at 5 keys; values stringified/truncated.
- **Run detail**: `graph_run_id` is display-only; no `/runs/...` route in this pass.
- **Lineage ids**: If `payload.ids` omits `evaluation_report_id`, lineage shows `—` even if a DB row exists elsewhere — snapshot payload is canonical for the API contract.
