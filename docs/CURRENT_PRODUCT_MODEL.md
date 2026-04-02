# Current KMBL product model (operational)

This document describes **how the system behaves today** in code (LangGraph orchestrator, Supabase-backed persistence, Next.js control plane). For philosophy and long-term vision, see [`00_KMBL_OVERVIEW.md`](00_KMBL_OVERVIEW.md) (non-normative for operators). For deeper state taxonomy, see [`05_STATE_AND_SNAPSHOTS.md`](05_STATE_AND_SNAPSHOTS.md).

## Engine

- **Graph runs** (`graph_run`) are the primary execution unit: **planner → generator → evaluator → decision → staging**, with iteration until limits or routing ends the loop.
- State is **persisted** (thread, checkpoints, role invocations, build artifacts, evaluation reports, `graph_run_event` timeline). Operators use **graph run detail** and **runs list** as the main record of what happened.

## Mutable surface: working staging and Live Habitat

- **`working_staging`** (per thread) holds the **live draft** HTML/asset payload that the generator applies to during iteration.
- The control plane **Live Habitat** page (`/habitat/live/{thread_id}`) is the human view of that **mutable** surface (preview iframe + metadata). It is **not** a frozen review artifact.

## Review snapshots (staging_snapshot)

- Immutable **`staging_snapshot`** rows are **frozen review candidates** (queue for human review, rating, approval flows).
- **Automatic** creation of a new row on each successful staging pass is **not** guaranteed. It depends on **`KMBL_STAGING_SNAPSHOT_POLICY`** (`always` | `on_nomination` | `never`) in orchestrator settings. **Default in code is `on_nomination`** — live evolution stays in **working staging** until nomination, materialize, or explicit `always` policy.
  - **`always`**: a review snapshot row is typically created when staging completes (subject to integrity checks).
  - **`on_nomination`**: a row is created only when the evaluator **nominates** (`marked_for_review` / nomination fields).
  - **`never`**: no automatic row; operators rely on **working staging** until they **materialize** (see below).
- When policy skips a row, the orchestrator records **`staging_snapshot_skipped`** on the graph run timeline. **Working staging** still updates; the live build may be ahead of the review queue.

## Materialize review snapshot from live

- Operators can create a **`staging_snapshot`** from the **current** working staging + last persisted provenance (`POST /orchestrator/working-staging/{thread_id}/review-snapshot`). The control plane proxies this as `POST /api/working-staging/{thread_id}/review-snapshot`.
- Use this when policy skipped automatic snapshots but a **frozen review row** is needed for the queue or publication FK.

## Publication (public release)

- **`publication_snapshot`** is **operator-gated** canon. Agents do **not** publish.
- Flows tie approval of a staging snapshot (or equivalent operator actions) to creating a publication snapshot; see orchestrator and control-plane **Publication** / **Public** surfaces.

## Output path today (extensible)

- The **primary production vertical** in v1 is **static frontend** (`static_frontend_file_v1`, identity URL scenarios). Other artifact families (composable UI, habitat manifests, routed **kmbl-image-gen**) exist in contracts and can expand without changing the core **working → optional review snapshot → operator publication** model.

## Terminology quick reference

| Term | Meaning |
|------|---------|
| **Graph run** | One persisted LangGraph execution (`graph_run_id`). |
| **Working staging** | Mutable draft per thread (`working_staging`). |
| **Live Habitat** | Control-plane UI for the mutable surface. |
| **Review snapshot / staging snapshot** | Immutable `staging_snapshot` row. |
| **Snapshot policy** | `staging_snapshot_policy` env — `always` / `on_nomination` / `never`. |
| **Materialize** | Operator POST to create a review snapshot from live working staging. |
| **Publication snapshot** | Public / canon release after operator approval. |
