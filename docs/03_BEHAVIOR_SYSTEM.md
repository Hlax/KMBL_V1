# Behavior System

## Overview

Behavior defines how KMBL operates over time.

Not just what it does, but how it evolves through graph execution, state transitions, and memory.

---

## Core Behaviors

- favor continuity over randomness
- avoid unnecessary change
- reflect before acting
- preserve meaningful ambiguity
- do not publish without explicit action

---

## Behavior Layers

KMBL behavior exists across three layers:

### 1. External Events
Things that enter the system:
- new identity source
- user instruction
- operator override
- scheduled trigger
- system alert

These events may start a new graph run or resume an existing thread.

### 2. Internal Graph Transitions
Routing decisions inside the runtime:
- whether an existing thread should resume or a new one should start
- whether context hydration or compaction is needed
- whether Planner should run
- whether Generator should run
- whether Evaluator should run
- whether the graph should pause, continue, retry, iterate, or branch

### 3. Durable State Evolution
Longer-term behavioral consequences:
- identity profile changes
- accepted memory changes
- live habitat evolution
- run history accumulation
- public snapshot lineage

---

## Agent Behaviors

Each agent follows its role constraints.

Agents:
- do not act without context
- do not redefine system rules
- do not operate outside graph state
- do not bypass orchestration

---

## Triggered Behaviors

Examples:

- new prompt or system event
  → resolve or create thread

- thread resumed
  → hydrate context from thread state and memory

- build requested
  → invoke Planner

- planner produces build specification
  → invoke Generator

- generator produces candidate system
  → invoke Evaluator

- evaluator returns fail or partial
  → re-invoke Generator with structured feedback

- evaluator returns pass
  → mark as eligible for publication review

- human review required
  → interrupt and wait for resume

- resume after interrupt
  → continue execution from updated state

---

## Resume Behavior

KMBL should not treat every event as a fresh start.

If a thread already contains the relevant working state, the runtime should resume from the current thread state rather than rebuild context from scratch.

---

## Replay and Fork Behavior

Past internal execution may be replayed or forked for debugging, recovery, or exploration.

Replay and fork are internal runtime behaviors.
They do not create public canon on their own.

---

## Context Continuity

KMBL does not reset context between executions.

Instead it maintains continuity through:

- thread state
- checkpoints
- context compaction

Context may be reduced or summarized,
but execution always resumes from prior state rather than restarting.

---

## Behavior Philosophy

KMBL should feel like:
- thinking
- refining
- evolving

Not:
- reacting blindly
- executing mechanically
- confusing temporary state with final truth