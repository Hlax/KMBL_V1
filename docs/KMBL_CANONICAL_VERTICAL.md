# KMBL Canonical Vertical — Identity URL → Static Frontend

**Operational surfaces (working staging vs review snapshots vs publication):** [`CURRENT_PRODUCT_MODEL.md`](CURRENT_PRODUCT_MODEL.md).

This document defines the single canonical end-to-end proof path for KMBL V1.
Everything else is additive or archival until this vertical is reliable.

Inspired by Anthropic's "Harness design for long-running application development":
**generator capability first, evaluator sophistication later.**

## Design Principles (Current Stage)

1. **Generator reliability is the top priority.** The generator must always have a path to emit a minimal valid package. One non-empty HTML file is enough.
2. **Handoffs are observable and durable.** Every intermediate artifact is persisted via checkpoints. Build candidates always reach the repository.
3. **Evaluator is a lightweight gate.** Pass and partial both stage. Fail iterates, then stages after max iterations. Only blocked prevents staging. No aesthetic rubrics, weighted metrics, or hard thresholds yet.
4. **Normalization is lenient.** Bad artifact rows are skipped (not crashed). Extra fields on artifacts are ignored. Recovery promotes files from `proposed_changes` and `updated_state` when `artifact_outputs` is empty.
5. **Stronger grading comes later.** Only after the generator consistently produces builds should we add evaluator sophistication — following the Dutch art museum lesson.

## The Canon

```
User provides a website URL
  ↓
KMBL extracts identity signals from the website
  ↓
Normalizes into a lightweight identity seed
  ↓
Planner creates a build spec (achievable, not over-specified)
  ↓
Generator produces static HTML/CSS/JS artifacts
  ↓
Evaluator performs lightweight gate check
  ↓  (pass or partial → stage immediately)
  ↓  (fail → iterate, then stage after max iterations)
  ↓  (blocked → interrupt)
Build candidate persisted with normalized artifacts
  ↓
Staging node applies to working_staging; optional staging_snapshot per KMBL_STAGING_SNAPSHOT_POLICY (or materialize from live)
  ↓
When a staging_snapshot row exists: static preview at /orchestrator/staging/{id}/static-preview
```

## How to Run Locally

### Prerequisites

```bash
cd services/orchestrator
pip install -e ".[dev]"
```

Environment variables for live runs (not needed for in-memory/stub):

```
KILOCLAW_BASE_URL=<KiloClaw gateway URL>
KILOCLAW_API_KEY=<KiloClaw API key>
SUPABASE_URL=<Supabase project URL>
SUPABASE_SERVICE_ROLE_KEY=<Supabase service role key>
```

### Run tests (fastest verification)

```bash
python -m pytest tests/test_identity_url_vertical.py -v
```

This runs 26 tests covering:
- Identity seed creation and persistence
- HTML signal extraction
- Recovery promotion (proposed_changes → artifact_outputs)
- Recovery from updated_state
- Lenient normalization (extra fields, bad rows, duplicates)
- Full vertical flow (seed → plan → generate → evaluate → stage → preview)
- Partial evaluation staging
- Minimal single-HTML artifact success
- Gallery harness non-downgrade
- Decision router logic (pass/partial/fail routing)

### Run full suite (regression check)

```bash
python -m pytest tests/ --ignore=tests/archive -v
```

201 tests, all passing.

### Start the orchestrator for live runs

```bash
cd services/orchestrator
uvicorn kmbl_orchestrator.api.main:app --host 0.0.0.0 --port 8000
```

### API Call — Identity URL Vertical

```bash
curl -X POST http://localhost:8000/orchestrator/runs/start \
  -H "Content-Type: application/json" \
  -d '{"identity_url": "https://example.com"}'
```

This automatically:
1. Fetches the URL and extracts identity signals
2. Creates IdentitySourceRecord + IdentityProfileRecord
3. Sets scenario to `kmbl_identity_url_static_v1`
4. Launches planner → generator → evaluator → staging

Response includes `graph_run_id`.

### Poll for completion

```bash
curl http://localhost:8000/orchestrator/runs/{graph_run_id}
```

Wait for `status: "completed"`. The response includes `staging_snapshot_id`.

### View the result

```bash
curl http://localhost:8000/orchestrator/staging/{staging_snapshot_id}/static-preview
```

Returns assembled HTML with inlined CSS/JS — the static page the generator built.

### Sample URLs for testing

| URL | Expected Result |
|-----|----------------|
| `https://example.com` | Minimal page (thin identity signals) |
| Any personal portfolio site | Richer page reflecting extracted identity |
| Non-existent URL | Degraded identity seed, still produces a page |

### What successful persistence looks like

After a successful run, these records exist:
- `ThreadRecord` with `identity_id`
- `GraphRunRecord` with `status: "completed"`
- `IdentitySourceRecord` + `IdentityProfileRecord`
- `BuildSpecRecord` with `spec_json.constraints.canonical_vertical = "static_frontend_file_v1"`
- `BuildCandidateRecord` with `artifact_refs_json` containing `static_frontend_file_v1` rows
- `EvaluationReportRecord` with `status: "pass"` or `"partial"`
- `StagingSnapshotRecord` with `snapshot_payload_json` including `metadata.frontend_static`

## Active Test Lanes

### 1. Full vertical end-to-end
- `test_identity_url_vertical.py::TestCanonicalVerticalFlow` (4 tests)
  - Full flow, recovery promotion, partial staging, minimal single HTML

### 2. Lenient normalization
- `test_identity_url_vertical.py::TestLenientNormalization` (3 tests)
  - Extra fields ignored, bad rows skipped, duplicates kept first

### 3. Recovery promotion
- `test_identity_url_vertical.py::TestRecoveryPromotion` (4 tests)
- `test_identity_url_vertical.py::TestUpdatedStateRecovery` (3 tests)

### 4. Decision routing
- `test_identity_url_vertical.py::TestDecisionRouterLogic` (3 tests)
- `test_identity_url_vertical.py::TestGalleryHarnessNonDowngrade` (1 test)

### 5. Static frontend normalization
- `test_static_frontend_pass.py` (10 tests)
- `test_static_preview_assembly.py` (6 tests)

### 6. Gallery/image (additive)
- `test_gallery_image_artifact_v1.py`
- `test_ui_gallery_strip_v1.py`

## Archived (Non-Canon)

Moved to `tests/archive/` and `scripts/archive/`.

## Success Criteria

A passing end-to-end run requires:
- [x] Identity URL accepted and fetched (or degraded with notes)
- [x] Identity seed produced (even if partial)
- [x] Planner returns build_spec with `canonical_vertical = "static_frontend_file_v1"`
- [x] Generator returns at least one `static_frontend_file_v1` artifact
- [x] Normalization persists a valid BuildCandidateRecord
- [x] Evaluator returns pass or partial (both reach staging)
- [x] Staging snapshot created
- [x] Static preview endpoint returns assembled HTML

## Failure Criteria

A run should only hard fail when:
- URL cannot be fetched AND no seed can be formed
- Planner returns nothing usable
- Generator returns all-empty output (truly empty — not just thin)
- Evaluation status is `blocked` (cannot evaluate at all)
- Staging snapshot cannot be assembled

Evaluator `fail` does NOT prevent staging — it iterates, then stages after max iterations.
Evaluator `partial` stages immediately.

## Future Expansion (Not Yet)

- Richer URL extraction (multi-page crawling, image analysis)
- Image reuse/remix in generator output
- Stronger evaluator grading (aesthetic rubrics, weighted metrics)
- Multi-iteration generator/evaluator loops with refined feedback
- Gaussian splat / 3D identity capture
- Full design system generation

These come after the generator consistently produces builds.

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `KILOCLAW_BASE_URL` | KiloClaw gateway URL | Yes (for live runs) |
| `KILOCLAW_API_KEY` | KiloClaw API key | Yes (for live runs) |
| `SUPABASE_URL` | Supabase project URL | No (in-memory if empty) |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key | No (in-memory if empty) |
| `ORCHESTRATOR_VERBOSE_LOGS` | Set to `1` for detailed logging | No |
| `KILOCLAW_TRANSPORT` | Set to `stub` for test mode | No |
