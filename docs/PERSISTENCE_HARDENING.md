# Persistence hardening (Supabase RPC + concurrency)

This document reflects the **implementation state** after the phased hardening work: what is atomic, what is concurrency-safe, and what remains best-effort.

## Phase 1 — Atomic write paths (Postgres RPC)

**Implemented SQL migration:** `supabase/migrations/20260402183000_atomic_staging_rpc.sql`

| RPC | Purpose |
|-----|---------|
| `kmbl_atomic_staging_node_persist` | Graph `staging_node`: `staging_checkpoint` rows (0..n) + `working_staging` upsert + optional `staging_snapshot` in **one** transaction |
| `kmbl_atomic_working_staging_approve` | Operator approve: `staging_checkpoint` + `publication_snapshot` + `working_staging` (frozen) in **one** transaction |
| `kmbl_atomic_upsert_working_staging` | Standalone `working_staging` upsert (e.g. operator rollback / fresh rebuild) |

**Orchestrator wiring:** `SupabaseRepository` calls these via `Client.rpc(...)`. In-memory tests use `Repository.atomic_*` methods wrapped in `InMemoryRepository.in_memory_write_snapshot()` (real rollback on exception only in-process).

**Still independent HTTP calls (not bundled in the RPCs above):** `graph_run_event`, `identity_profile` upserts from staging, checkpoints/roles elsewhere in the graph, operator `staging_snapshot` materialize (single-row insert), publication from `/publication` routes, etc.

**Schema:** `working_staging.last_alignment_score` is added when missing so Supabase mirrors evaluator alignment on the live row.

## Phase 2 — Concurrency (database advisory locks)

**Mechanism:** `kmbl_thread_advisory_xact_lock(thread_id)` uses `pg_advisory_xact_lock` with a deterministic 64-bit key derived from the thread UUID (`md5` hex → `bit(64)::bigint`). The lock is **transaction-scoped** (released when the RPC transaction commits or rolls back), which is compatible with pooled PostgREST connections.

**Applied inside:** all three RPCs above, so cross-process writes to the same thread for those code paths serialize.

**Process-local `Repository.thread_lock`:** Still used around graph execution in `graph.app` for **single-worker** fairness; it does **not** coordinate across multiple API processes. Cross-process safety for the critical staging rows relies on the RPC advisory locks, not the Python mutex.

**Not serialized by DB locks:** the full graph run from planner through evaluator (except the staging bundle), duplicate-start handling, and other single-row writes unless future RPCs add locks.

## Phase 3 — Mutation / evaluation semantics & observability

**Evaluator vs staging:**

- `staging_node` documents that `pass` / `partial` / `fail` are all stageable; blocked evaluations are rejected earlier.
- Whether an immutable `staging_snapshot` row is written is governed by **nomination + `staging_snapshot_policy`**, not solely by evaluator outcome.

**Operator vs graph:**

- Graph path: `atomic_persist_staging_node_writes` (Supabase RPC) + timeline events with `persistence: supabase_rpc` in payloads where applicable.
- Operator HTTP: rollback, materialize, and **working-staging approve** (`POST .../working-staging/{id}/approve`) append `graph_run_event` rows when `graph_run_id` is known, with `mutation_path` and `persistence` in the payload. New event type: `operator_review_snapshot_materialized`.
- **Staging-snapshot approve** (`POST .../staging/{staging_snapshot_id}/approve`) remains a separate, evaluator-audit-gated status transition on the immutable review row (not the same RPC as freezing live working staging).

**Read model:** `docs` graph-run timeline and operator-actions helpers recognize rollback, materialize, and publication events where listed in `graph_run_detail_read_model.py` / `operator_action_read_model.py`.

## Rollout

1. Apply Supabase migrations (includes new RPCs + `GRANT EXECUTE … TO service_role`).
2. Deploy orchestrator build that includes the updated `SupabaseRepository`.
3. No public API contract changes; behavior should match prior success paths with stronger atomicity on the bundled writes.

## Implementation report (concise)

| Area | Status |
|------|--------|
| **Truly atomic (Supabase)** | `staging_node` checkpoint + working_staging + optional staging_snapshot; operator approve triple-write; standalone working_staging upsert runs under the same thread lock as those flows |
| **Concurrency-safe** | Thread-scoped `pg_advisory_xact_lock` inside the RPCs above |
| **Best-effort / future** | Planner/generator/evaluator/post-run persistence remain **sequential PostgREST** calls (no cross-call rollback); `SupabaseRepository.in_memory_write_snapshot()` **raises** if ever used; graph-wide cross-process serialization; bundling identity/events with staging RPC; SQLAlchemy/ORM (explicitly out of scope) |

## Write snapshot API (semantic safety)

- **`InMemoryRepository.in_memory_write_snapshot()`** — copy-on-enter / restore-on-exception for **tests and local dev only**.
- **`SupabaseRepository.in_memory_write_snapshot()`** — always raises **`WriteSnapshotNotSupportedError`**; there is no silent no-op “transaction”.
- **Production graph nodes** do not wrap persistence in a snapshot scope; comments in code state that PostgREST writes are sequential unless using RPC helpers.

**Live validation:** run `python scripts/validate_supabase_rpc_live.py` with real credentials; record output in `docs/LIVE_VALIDATION_REPORT.md`.
