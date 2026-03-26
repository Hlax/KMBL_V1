# Runtime State and Reducers

## Purpose

Define how runtime state is:

- structured
- updated
- persisted
- reduced across graph execution

This document bridges:

- LangGraph execution
- KMBL data model
- checkpoint system
- iteration behavior

---

## Core Principle

State is the single source of truth during execution.

- nodes read from state
- nodes write to state
- reducers merge updates into state

No direct node-to-node communication.

---

# 1. State Layers

KMBL runtime state exists across three layers:

---

## 1.1 In-Memory Graph State

Ephemeral state passed between nodes.

Contains:

- identity_context
- memory_context
- build_spec
- build_candidate
- evaluation_report
- iteration_index
- decision

This state lives only during graph execution.

---

## 1.2 Checkpoint State

Persisted runtime state.

Stored in:

- `checkpoint.state_json`

Purpose:

- resume execution
- replay execution
- debug execution

---

## 1.3 Database Records

Structured persisted outputs.

Examples:

- build_spec
- build_candidate
- evaluation_report

These are normalized records.

---

# 2. State Shape

'''json
{
  "thread_id": "uuid",
  "graph_run_id": "uuid",

  "identity_context": {},
  "memory_context": {},

  "current_state": {},
  "compacted_context": {},

  "build_spec": null,
  "build_candidate": null,
  "evaluation_report": null,

  "iteration_index": 0,
  "max_iterations": 3,

  "decision": null,
  "status": "running"
}
'''

---

# 3. Reducer Model

Reducers define how node outputs merge into state.

---

## 3.1 build_spec reducer

'''json
state.build_spec = incoming.build_spec
'''

---

## 3.2 build_candidate reducer

'''json
state.build_candidate = incoming.build_candidate
'''

---

## 3.3 evaluation_report reducer

'''json
state.evaluation_report = incoming.evaluation_report
'''

---

## 3.4 iteration reducer

'''json
if state.decision == "iterate":
  state.iteration_index += 1
'''

---

## 3.5 decision reducer

'''json
state.decision = incoming.decision
'''

---

## 3.6 context reducer

'''json
state.compacted_context = compact(state)
'''

---

# 4. Persistence Strategy

## When to Persist

KMBL must persist:

- before role invocation
- after role completion
- before interrupt
- after decision

---

## What to Persist

### Checkpoint

'''json
{
  "thread_id": "...",
  "state_json": {},
  "context_compaction_json": {}
}
'''

---

### Role Invocation

'''json
{
  "role_type": "planner",
  "input_payload": {},
  "output_payload": {},
  "status": "completed"
}
'''

---

### Build Records

- build_spec
- build_candidate
- evaluation_report

---

# 5. State Flow Example

## Single Pass

1. planner_node
→ state.build_spec populated

2. generator_node
→ state.build_candidate populated

3. evaluator_node
→ state.evaluation_report populated

4. decision_router
→ state.decision set

---

## Iteration Pass

1. decision = iterate

2. iteration_index += 1

3. generator_node receives:

'''json
{
  "iteration_feedback": state.evaluation_report
}
'''

4. repeat loop

---

# 6. Context Compaction

## Purpose

Prevent state explosion.

---

## Strategy

Before each role invocation:

- summarize previous outputs
- keep only relevant signals
- drop redundant data

---

## Output

'''json
{
  "summary": "...",
  "key_signals": [],
  "active_constraints": []
}
'''

---

## Rule

Compaction must not remove:

- build_spec
- evaluation issues
- active constraints

---

# 7. Interrupt State

When interrupt triggered:

- state.status = "paused"
- state.decision = "interrupt"

Checkpoint is saved.

---

## Resume Behavior

On resume:

- load checkpoint.state_json
- restore state
- continue execution

---

# 8. State Integrity Rules

## Rule 1

State must always be valid JSON.

---

## Rule 2

Reducers must be deterministic.

---

## Rule 3

No node may delete critical fields.

---

## Rule 4

State must be checkpoint-safe at all times.

---

## Rule 5

All external outputs must be persisted.

---

# 9. Minimal v1 Scope

Start with:

- build_spec reducer
- build_candidate reducer
- evaluation_report reducer
- iteration reducer

Skip:

- advanced compaction
- complex state merging

---

# 10. Future Extensions

- partial state diffing
- streaming reducers
- multi-branch state trees
- forked execution paths
- state versioning

Not required for v1.