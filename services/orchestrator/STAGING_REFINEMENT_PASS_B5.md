# Staging Refinement (Pass B.5)

Pass B.5 tightens **preview-integrity failure semantics**, aligns **product-facing staging reads** with the orchestrator persisted model, documents a **versioned staging payload**, adds **review readiness** on GET staging, and normalizes **timeline blocked** metadata.

## Files changed

| Layer | Path |
|--------|------|
| Errors | `src/kmbl_orchestrator/errors.py` — `StagingIntegrityFailed` |
| Taxonomy | `src/kmbl_orchestrator/contracts/normalized_errors.py` — `staging_integrity` kind, `staging_integrity_failure()` |
| Failure read model | `src/kmbl_orchestrator/runtime/run_failure_view.py` — allow `staging_integrity` |
| Graph | `src/kmbl_orchestrator/graph/app.py` — catch `StagingIntegrityFailed`, interrupt envelope, timeline payloads |
| Payload contract | `src/kmbl_orchestrator/staging/build_snapshot.py` — `StagingSnapshotPayloadV1` sections (`ids`, `summary`, `evaluation`, `preview`, `artifacts`, `metadata`) |
| API | `src/kmbl_orchestrator/api/main.py` — `review_readiness` on GET staging; background handler ignores `StagingIntegrityFailed` (no duplicate generic interrupt) |
| Product | `apps/control-plane/app/api/staging/[stagingSnapshotId]/route.ts` — proxy to orchestrator |
| Tests | `tests/test_staging_pass_b.py` |

## Semantic changes

1. **Preview / staging gate failures**  
   Preview validation and other staging final checks raise **`StagingIntegrityFailed`** (`error_kind` at interrupt: **`staging_integrity`**, sub-**`reason`**: `preview_integrity` | `staging_integrity` | `persistence_error`).  
   No generic `RuntimeError` for those paths; `run_graph` writes a structured interrupt (same pattern as role failures, without `failure_phase`).

2. **GET `/orchestrator/runs/{id}`**  
   Failed runs with staging interrupts expose **`error_kind: staging_integrity`** and **`failure.reason`** via existing `build_run_failure_view` + interrupt `failure` blob.

3. **GET `/orchestrator/staging/{id}`**  
   Adds **`review_readiness`**: `{ "ready", "basis", "staging_status" }` derived from the persisted row (`ready` when `staging_snapshot.status == review_ready`).

4. **Timeline**  
   - `staging_snapshot_blocked` includes **`error_kind`: `staging_integrity`** where applicable and a normalized **`reason`** (`evaluator_not_pass`, `preview_integrity`, `staging_integrity`, `persistence_error`).  
   - `staging_snapshot_created` includes **`review_ready`: true** when the snapshot row is written.

5. **Snapshot payload**  
   Stored JSON is **`version: 1`** with nested sections; no raw KiloClaw `raw_payload_json` in the payload.

## API changes

| Endpoint | Change |
|----------|--------|
| `GET /orchestrator/staging/{id}` | Response includes `review_readiness`. Payload shape under `snapshot_payload_json` is v1 sections (see `StagingSnapshotPayloadV1`). |
| `GET /api/staging/{id}` (control-plane) | **New** — forwards to orchestrator; same JSON/status codes (404 if absent). |

## Test commands

```bash
cd services/orchestrator
python -m pytest tests/ -q
```

## Manual verification

- [ ] Run with a bad `preview_url` after evaluator pass: run fails with `staging_integrity`, not `graph_error`; GET run shows `error_kind` / `failure.reason`.  
- [ ] GET `/orchestrator/staging/{uuid}` for a successful stub run: `review_readiness.ready` is true, payload has `version: 1`.  
- [ ] From control-plane, `GET /api/staging/{uuid}` matches orchestrator body for 200/404.  
- [ ] Timeline shows `staging_snapshot_blocked` with `reason` + `error_kind` where expected.

## Known limitations

- Control-plane route is a **transparent proxy**; it does not cache or re-derive staging from checkpoints.  
- **Publication** flow unchanged.  
- No auth changes on the new route (same as other orchestrator proxies).
