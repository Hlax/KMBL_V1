# Staging mutation semantics (working surface vs snapshots)

**See also:** [`CURRENT_PRODUCT_MODEL.md`](CURRENT_PRODUCT_MODEL.md) (snapshot policy, materialize-from-live).

## Working staging (mutable)

[`WorkingStagingRecord`](../services/orchestrator/src/kmbl_orchestrator/domain.py) holds the **live draft** for a thread. Updates go through [`staging/working_staging_ops.py`](../services/orchestrator/src/kmbl_orchestrator/staging/working_staging_ops.py):

- **`choose_update_mode` / `choose_update_mode_with_pressure`**: **rebuild** when there is no surface, empty revision, evaluator **fail**, staging **pressure** (too many patches since rebuild), or **guardrails** demand a clean slate; otherwise **patch** (merge artifacts by path).
- **`apply_generator_to_working_staging`**: applies the build candidate and evaluation to the working payload.
- **Staging checkpoints** (`StagingCheckpointRecord`): recovery points (pre-rebuild, post-patch milestones, etc.), distinct from LangGraph `CheckpointRecord` (execution forensics).

## Staging snapshots (immutable review rows)

When the staging node applies a build candidate to **working staging**, it may **also** persist a [`StagingSnapshotRecord`](../services/orchestrator/src/kmbl_orchestrator/domain.py) (`snapshot_payload_json` for human review, ratings, promotion)—**depending on** orchestrator **`KMBL_STAGING_SNAPSHOT_POLICY`** (`always` | `on_nomination` | `never`):

- **`always`**: a new review snapshot row is created when staging completes and integrity checks pass (usual case).
- **`on_nomination`**: a row is created only when the evaluator **nominates** for review (`marked_for_review` / nomination extraction). Otherwise no new `staging_snapshot` row; the orchestrator emits **`staging_snapshot_skipped`** on the graph run timeline.
- **`never`**: no automatic review snapshot row; **`staging_snapshot_skipped`** is recorded. **Working staging** still holds the live build.

Operators can **materialize** a review snapshot from the current live working staging when policy skipped automatic rows: `POST /orchestrator/working-staging/{thread_id}/review-snapshot` (see [`routes_working_staging.py`](../services/orchestrator/src/kmbl_orchestrator/api/routes_working_staging.py), [`materialize_review_snapshot.py`](../services/orchestrator/src/kmbl_orchestrator/staging/materialize_review_snapshot.py)).

## Publication

[`PublicationSnapshotRecord`](../services/orchestrator/src/kmbl_orchestrator/domain.py) is **immutable canon** created from an approved staging snapshot (see [`publication/`](../services/orchestrator/src/kmbl_orchestrator/publication/) and [`publication/delivery.py`](../services/orchestrator/src/kmbl_orchestrator/publication/delivery.py) for local HTML delivery).

**Rule of thumb:** mutate **working staging** during iteration; **snapshot** for review; **publication** for shipped artifacts.
