# State and Snapshots

**Operational product model (current build):** [`CURRENT_PRODUCT_MODEL.md`](CURRENT_PRODUCT_MODEL.md).

## Overview

KMBL distinguishes between mutable runtime state and immutable product snapshots.

---

## State Types

### Working State (Mutable)
- current habitat working state
- working identity synthesis
- draft changes
- active planner outputs
- candidate generator outputs under review

This state is actively evolving during runtime.

---

### Thread State (Durable Runtime Continuity)
- accumulated graph state for a thread
- resumable short-term memory
- interrupt and resume context
- prior step outputs needed for continuation

Thread state supports continuity of execution.

---

### Graph runs (durable execution records)
- persisted `graph_run` rows: status, timing, linkage to thread and identity
- associated `role_invocation`, build/eval artifacts, and append-only `graph_run_event` timeline

Graph runs are the **operator-visible history** of execution. They are **not** immutable product canon (that is **publication** / approved snapshots), but they are **authoritative** as the record of what the orchestrator did—not disposable “logs only.”

---

### Build Artifacts (Runtime Outputs)

- planner specification bundles
- generator output bundles
- evaluator reports
- sandbox execution results
- preview metadata

These artifacts:

- are produced during execution
- may be stored for debugging and review
- are not automatically canon
- may be used to construct staging views

They exist between working state and snapshots.

They are runtime outputs, not product truth.

---

### Memory
- selected durable identity signals
- accepted cross-thread knowledge

Memory shapes future behavior.

---

### Checkpoints (Runtime Persistence)
- saved graph state within a thread
- used for resume, replay, fork, and recovery

Checkpoints are runtime artifacts, not public artifacts.

---

### Snapshots (Immutable product states)

Two distinct snapshot families matter in the current implementation:

- **`staging_snapshot`** — frozen **review** rows (staging review queue); optional per `staging_snapshot_policy`; see [`CURRENT_PRODUCT_MODEL.md`](CURRENT_PRODUCT_MODEL.md).
- **`publication_snapshot`** — operator-approved **public / canon** releases.

Older prose below refers to “product snapshots” in the abstract; map mentally to **staging** vs **publication** rows in the database.

Snapshots cannot be modified after write.

---

## Publication Boundary

Publishing creates a snapshot.

Nothing becomes public unless:
- explicitly selected
- intentionally frozen
- written as a product-level snapshot

---

## Non-Equivalence Rule

Checkpoints are not snapshots.

A checkpoint preserves execution continuity.
A snapshot preserves product truth.

One is for runtime persistence.
The other is for canon, publication, and history.

---

## Rule

Only product snapshots are immutable canon.

Everything else may evolve.