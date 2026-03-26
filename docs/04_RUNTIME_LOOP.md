# Runtime Graph (Harness Model)

## Overview

KMBL operates as a stateful runtime graph.

Execution is not a fixed sequence.
It is a controlled loop driven by state, evaluation, and decisions.

---

## Core Model

KMBL runtime consists of:

- graph state
- nodes
- edges
- reducers
- checkpoints
- threads
- interrupts
- side-effect boundaries

The graph is the execution model.
The thread is the continuity container.
The checkpoint preserves runtime state.

---

## Harness Flow

A common execution flow:

1. Event Ingress
- user input
- system trigger
- resume request

2. Thread Resolution
- continue existing thread or create new

3. Context Hydration
- load thread state
- apply memory
- apply context compaction

4. Planner Invocation
- generate structured build spec

5. Generator Invocation
- produce system build

6. Evaluator Invocation
- perform full-system review

7. Decision

Based on evaluation:

- iterate → return to generator
- interrupt → wait for human input
- finalize → mark ready for publication review
- stop → no further action

---

## External Role Execution

Role execution may occur outside KMBL.

In this system:

- Planner, Generator, Evaluator are executed via KiloClaw
- KMBL invokes them as external workers
- KMBL retains control of:
  - thread
  - state
  - checkpoints
  - iteration

---

## Iteration Loop

The runtime supports iterative convergence.

- generator produces candidate
- evaluator reviews
- feedback loops back into generator

No context reset occurs between iterations.

---

## Context Strategy

KMBL preserves continuity through:

- thread state
- checkpoints
- context compaction

KMBL resumes execution rather than restarting from scratch.

---

## Runtime Units

### Thread
A continuous execution context.

### Checkpoint
A saved runtime state within a thread.

### Run
A single execution step or invocation.

### Interrupt
A pause point for human input or approval.

---

## Continuous vs Discrete

Continuous:
- identity evolution
- thread continuity
- memory shaping

Discrete:
- planner execution
- generator execution
- evaluator execution
- publication

---

## Runtime Rule

KMBL should feel:

- continuous
- stateful
- resumable
- iterative

Not:

- reset-driven
- strictly linear
- stateless