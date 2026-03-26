# LangGraph Orchestrator Specification

## Purpose

Define the runtime orchestration layer for KMBL using LangGraph.

This document specifies:

- graph structure
- node responsibilities
- state shape
- reducer behavior
- iteration loop
- interrupt handling
- persistence integration

This is the executable layer of the system.

---

## Core Principle

KMBL controls execution.

- the graph decides what runs next
- agents do not control flow
- all transitions are state-driven

---

# 1. Graph Overview

## High-Level Flow

event → thread → context → planner → generator → evaluator → decision

The system loops until:

- evaluation passes
- iteration limit reached
- interrupt triggered

---

## Node Map

1. event_ingress
2. thread_resolver
3. context_hydrator
4. checkpoint_pre
5. planner_node
6. generator_node
7. evaluator_node
8. decision_router
9. interrupt_node (optional)
10. staging_node
11. publication_node (optional)

---

# 2. Graph State

## State Shape

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
  "interrupt_reason": null,

  "status": "running"
}
'''

---

## State Principles

- state is the only communication layer
- nodes do not call each other directly
- reducers merge outputs into state

---

# 3. Node Specifications

---

## 3.1 event_ingress

### Purpose

Normalize incoming event.

### Input

- raw user input or system trigger

### Output

- structured event payload

---

## 3.2 thread_resolver

### Purpose

Resolve or create thread.

### Behavior

- find existing thread if relevant
- otherwise create new thread

### Side Effects

- may create thread record

---

## 3.3 context_hydrator

### Purpose

Load runtime context.

### Behavior

- load thread state
- load identity profile
- load memory
- apply compaction

### Output

- identity_context
- memory_context
- compacted_context

---

## 3.4 checkpoint_pre

### Purpose

Persist pre-execution state.

### Behavior

- create checkpoint
- store state_json

---

## 3.5 planner_node

### Purpose

Invoke Planner (KiloClaw)

### Input

'''json
{
  "thread_id": "...",
  "identity_context": {},
  "memory_context": {},
  "event_input": {},
  "current_state_summary": {}
}
'''

### Behavior

- create role_invocation (planner)
- call KiloClaw Planner config
- receive response

### Output

- build_spec
- constraints
- success_criteria
- evaluation_targets

### Persistence

- store role_invocation
- store build_spec

---

## 3.6 generator_node

### Purpose

Invoke Generator (KiloClaw)

### Input

'''json
{
  "thread_id": "...",
  "build_spec": {},
  "current_working_state": {},
  "iteration_feedback": {}
}
'''

### Behavior

- create role_invocation (generator)
- call KiloClaw Generator config

### Output

- proposed_changes
- artifact_outputs
- updated_state
- sandbox_ref
- preview_url

### Persistence

- store role_invocation
- store build_candidate

---

## 3.7 evaluator_node

### Purpose

Invoke Evaluator (KiloClaw)

### Input

'''json
{
  "thread_id": "...",
  "build_candidate": {},
  "success_criteria": [],
  "evaluation_targets": []
}
'''

### Behavior

- create role_invocation (evaluator)
- call KiloClaw Evaluator config

### Output

- status
- summary
- issues
- metrics

### Persistence

- store role_invocation
- store evaluation_report

---

## 3.8 decision_router

### Purpose

Determine next step.

### Logic

'''json
if status == "pass":
  decision = "stage"

elif status in ["fail", "partial"]:
  if iteration_index < max_iterations:
    decision = "iterate"
  else:
    decision = "interrupt"

elif status == "blocked":
  decision = "interrupt"
'''

### Output

- decision
- iteration_index (increment if iterate)

---

## 3.9 interrupt_node

### Purpose

Pause execution.

### Behavior

- set thread status = paused
- store interrupt_reason
- create checkpoint

### Resume

- resumes same thread
- re-enters graph at decision_router or generator_node

---

## 3.10 staging_node

### Purpose

Create staging snapshot.

### Behavior

- assemble snapshot_payload
- attach preview_url
- store staging_snapshot

### Output

- staging_snapshot_id

---

## 3.11 publication_node (optional)

### Purpose

Create immutable snapshot.

### Behavior

- requires explicit trigger
- creates publication_snapshot
- links parent snapshot

---

# 4. Reducers

Reducers merge node outputs into state.

---

## build_spec reducer

'''json
state.build_spec = new.build_spec
'''

---

## build_candidate reducer

'''json
state.build_candidate = new.build_candidate
'''

---

## evaluation_report reducer

'''json
state.evaluation_report = new.evaluation_report
'''

---

## iteration reducer

'''json
if decision == "iterate":
  state.iteration_index += 1
'''

---

# 5. Iteration Loop

## Loop Path

generator → evaluator → decision → generator

---

## Exit Conditions

- evaluation status = pass
- iteration_index >= max_iterations
- interrupt triggered

---

## Feedback Injection

Generator receives:

'''json
{
  "iteration_feedback": state.evaluation_report
}
'''

---

# 6. Interrupt Handling

## When triggered

- evaluation blocked
- iteration exhausted
- human approval required

---

## Behavior

- pause thread
- persist checkpoint
- wait for external input

---

## Resume

- reload checkpoint
- continue graph

---

# 7. Persistence Integration

Each node must:

1. create role_invocation record
2. store input payload
3. store output payload
4. update status timestamps

---

## Key Rule

KMBL persists all meaningful outputs.

Nothing important should only exist in KiloClaw.

---

# 8. Minimal v1 Graph

Start with:

- thread_resolver
- context_hydrator
- checkpoint_pre
- planner_node
- generator_node
- evaluator_node
- decision_router
- staging_node

Skip:

- publication_node
- advanced interrupt routing

---

# 9. Design Constraints

- no direct agent-to-agent calls
- no hidden state mutation
- no context reset between iterations
- all transitions must be explicit
- all outputs must be persisted

---

# 10. First Working Test

A valid v1 run:

1. event → planner
2. planner → build_spec
3. generator → build_candidate
4. evaluator → evaluation_report
5. decision → stage
6. staging_snapshot created

If this works end-to-end, the system is valid.