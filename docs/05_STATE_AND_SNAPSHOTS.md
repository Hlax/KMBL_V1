# State and Snapshots

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

### Runs (Historical)
- records of graph activity
- summaries and outputs
- node-level execution history

Runs are logs, not truth.

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

### Snapshots (Immutable Product States)
- frozen moments of KMBL
- public states
- milestone states
- canonical historical releases

Snapshots cannot be modified.

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