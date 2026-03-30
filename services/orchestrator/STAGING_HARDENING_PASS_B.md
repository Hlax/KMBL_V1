# Staging + Output Integrity (Pass B)

Pass B builds on **Runtime Hardening (Pass A)**. It makes planner persistence robust to sparse LLM `build_spec`, rejects meaningless generator output, gates `staging_snapshot` on evaluator **pass** only, validates preview rules before staging, builds deterministic snapshot payloads from persisted rows, and exposes **only** persisted staging via the orchestrator API.

## Files changed (primary)

| Area | Files |
|------|--------|
| Planner normalization | `src/kmbl_orchestrator/contracts/planner_normalize.py` |
| Generator / preview checks | `src/kmbl_orchestrator/staging/integrity.py` |
| Snapshot payload | `src/kmbl_orchestrator/staging/build_snapshot.py` |
| Graph wiring | `src/kmbl_orchestrator/graph/app.py` |
| Persistence | `src/kmbl_orchestrator/persistence/repository.py`, `supabase_repository.py` |
| Evaluator / planner persist validation | `src/kmbl_orchestrator/contracts/persistence_validate.py` |
| Domain | `src/kmbl_orchestrator/domain.py` (`StagingSnapshotRecord`, `EvaluationReportRecord.summary`) |
| Timeline | `src/kmbl_orchestrator/runtime/run_events.py` |
| API | `src/kmbl_orchestrator/api/main.py` — `GET /orchestrator/staging/{staging_snapshot_id}` |
| DB | `supabase/migrations/20260329180000_staging_snapshot.sql` |
| Tests | `tests/test_staging_pass_b.py`, `tests/test_runtime_hardening.py` (planner malformed case) |

**Note:** Product UI `GET /api/staging/{id}` (control-plane) was **not** changed (Pass B scope: orchestrator-only API for persisted staging truth).

## Behavior changes

1. **Planner persistence fallback**  
   After a successful planner invoke, `build_spec` is copied through `normalize_build_spec_for_persistence` (defaults `type` → `generic`, `title` → `Untitled Build`, trim strings). Missing fields are listed under `raw_payload_json._kmbl_planner_metadata.normalized_missing_fields` on the saved `build_spec` row. Persistence validation runs **after** this step, so missing type/title no longer fail the run.

2. **Generator integrity**  
   Before persistence validation, `validate_generator_output_for_candidate` requires at least one non-empty primary field among `proposed_changes`, `artifact_outputs`, `updated_state`, and enforces `sandbox_ref` / `preview_url` as `str` or `null`. On failure the role invocation is stored as failed with `error_kind: contract_validation` and `RoleInvocationFailed` is raised.

3. **Evaluator gating**  
   `staging_node` loads `BuildCandidate`, `EvaluationReport`, `BuildSpec`, and `Thread` from the repository, asserts `evaluation_report.status == "pass"`, runs `validate_preview_integrity`, then builds and saves `StagingSnapshotRecord`. No snapshot is written on non-pass paths.

4. **Decision timeline**  
   When evaluation status is not `pass`, a `staging_snapshot_blocked` event is appended (reason `evaluator_not_pass`). Preview failures in `staging_node` append `staging_snapshot_blocked` with reason `preview_integrity`. Successful writes append `staging_snapshot_created`.

5. **Deterministic snapshot payload**  
   `build_staging_snapshot_payload` uses only persisted records (no extra I/O or generator calls).

6. **GET staging**  
   `GET /orchestrator/staging/{id}` returns the persisted row fields only; **404** if absent.

## New / notable helpers

- `normalize_build_spec_for_persistence(build_spec) -> tuple[dict, list[str]]` — returns normalized spec and field names that were defaulted.
- `validate_generator_output_for_candidate(output: dict)`
- `validate_preview_integrity(build_candidate, evaluation_report)`
- `build_staging_snapshot_payload(build_candidate=..., evaluation_report=..., thread=..., build_spec=...)`

Repository additions: `get_thread`, `get_build_candidate`, `get_evaluation_report`, `save_staging_snapshot`, `get_staging_snapshot`.

## Test instructions

From `services/orchestrator`:

```bash
python -m pytest tests/ -q
```

Focused:

```bash
python -m pytest tests/test_staging_pass_b.py -q
```

## Manual verification checklist

- [ ] Start a run with KiloClaw **stub**; confirm run completes and timeline includes `staging_snapshot_created`.
- [ ] Poll `GET /orchestrator/staging/{staging_snapshot_id}` with the id from the final graph state; response matches DB and includes `snapshot_payload_json`.
- [ ] Induce evaluator `fail` / `partial` (custom provider); confirm **no** `staging_snapshot_created`, timeline has `staging_snapshot_blocked`.
- [ ] Apply Supabase migration `20260329180000_staging_snapshot.sql` in non-local environments before relying on Supabase-backed staging rows.

## Success criteria (Pass B)

- Planner rows persist with safe defaults when type/title are missing.
- Generator cannot persist empty “shell” candidates.
- Staging snapshots exist only when evaluation **passes** and preview rules hold.
- Snapshot payload is deterministic from stored rows.
- Staging read API reflects **persisted** truth only.
