# Agent Roles (Harness Architecture)

## Overview

Agents are internal execution roles within KMBL.

They are not workflows.
They do not control execution order.
They do not call each other.

They are **specialized transformation roles** operating within a graph.

KMBL orchestrates everything.

Agents:
- receive structured state
- perform scoped work
- return structured updates

---

## Core Principle

Agents are **capability modules, not workflow owners**.

- The graph decides what runs next
- State is the interface between roles
- Execution is always mediated by KMBL

---

## Role Model

KMBL operates as a **build harness**, not a linear pipeline.

input → planner → generator → evaluator → iteration → publication

Identity and memory provide context.
They are not required stages in every run.

---

## Role Execution Environment

Agent roles may be executed in an external system.

In this architecture:

- Planner, Generator, and Evaluator are hosted as **distinct KiloClaw configurations**
- KMBL invokes them as external role workers
- KMBL retains authority over:
  - thread lifecycle
  - state
  - checkpoints
  - iteration
  - publication

Execution location does not change orchestration authority.

---

## Primary Roles

### Planner Agent

Role:
Expand intent into a structured build specification.

Inputs:
- user prompt or system event
- thread state
- identity context
- memory
- existing system state

Outputs:
- `build_spec`
- `constraints`
- `success_criteria`
- `evaluation_targets`

Constraints:
- does not generate code or UI
- does not execute changes
- does not validate results

---

### Generator Agent

Role:
Execute the build.

Inputs:
- `build_spec`
- current system state
- evaluator feedback (if iterating)
- compacted thread context

Outputs:
- `proposed_changes`
- `artifact_outputs`
- `updated_state`

Constraints:
- does not define scope
- does not approve correctness
- does not publish

---

### Evaluator Agent

Role:
Perform full-system evaluation.

Inputs:
- full system output
- `success_criteria`
- `evaluation_targets`

Outputs:
- `evaluation_report`
- `issues[]`
- `status: pass | fail | partial`

Constraints:
- does not fix issues
- does not modify system state
- does not redefine scope

---

## Iteration Model

Evaluation feeds back into generation.

1. Planner defines spec
2. Generator builds
3. Evaluator reviews

If not pass:
→ Generator revises using evaluator feedback

Repeat until:
- pass
- max iterations reached
- interrupt triggered

---

## Human Role

Humans are explicit interrupt boundaries.

They may:
- approve publication
- override direction
- resolve ambiguity

They are not part of automated role execution.

---

## Shared-State Rule

All roles operate through graph state.

- no direct handoffs
- no hidden communication

KMBL:
- decides what state is read
- decides what state is written
- decides what runs next

---

## Relationship to Identity

Identity is not a role.

It is:
- context
- evolving signal system
- memory input

It informs planning.
It does not control execution.

---

## Relationship to Snapshots

Roles operate on mutable state.

Only publication creates immutable truth.

Snapshots remain the only canon boundary.