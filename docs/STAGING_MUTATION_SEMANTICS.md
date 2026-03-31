# Staging mutation semantics (working surface vs snapshots)

## Working staging (mutable)

[`WorkingStagingRecord`](../services/orchestrator/src/kmbl_orchestrator/domain.py) holds the **live draft** for a thread. Updates go through [`staging/working_staging_ops.py`](../services/orchestrator/src/kmbl_orchestrator/staging/working_staging_ops.py):

- **`choose_update_mode` / `choose_update_mode_with_pressure`**: **rebuild** when there is no surface, empty revision, evaluator **fail**, staging **pressure** (too many patches since rebuild), or **guardrails** demand a clean slate; otherwise **patch** (merge artifacts by path).
- **`apply_generator_to_working_staging`**: applies the build candidate and evaluation to the working payload.
- **Staging checkpoints** (`StagingCheckpointRecord`): recovery points (pre-rebuild, post-patch milestones, etc.), distinct from LangGraph `CheckpointRecord` (execution forensics).

## Staging snapshots (immutable review rows)

Each graph run that reaches **staging** produces a [`StagingSnapshotRecord`](../services/orchestrator/src/kmbl_orchestrator/domain.py) with `snapshot_payload_json` for human review, ratings, and promotion.

## Publication

[`PublicationSnapshotRecord`](../services/orchestrator/src/kmbl_orchestrator/domain.py) is **immutable canon** created from an approved staging snapshot (see [`publication/`](../services/orchestrator/src/kmbl_orchestrator/publication/) and [`publication/delivery.py`](../services/orchestrator/src/kmbl_orchestrator/publication/delivery.py) for local HTML delivery).

**Rule of thumb:** mutate **working staging** during iteration; **snapshot** for review; **publication** for shipped artifacts.
