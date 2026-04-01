# KMBL Overview

**Normative product behavior (operators, engineers):** see [`CURRENT_PRODUCT_MODEL.md`](CURRENT_PRODUCT_MODEL.md). This page is **positioning and intent**, not a substitute for runtime semantics.

## What KMBL Is

KMBL is a living, evolving digital entity.

It:
- learns from identity sources
- develops internal understanding over time
- expresses itself through a mutable habitat
- produces moments that can be captured as snapshots

KMBL is not a collection of tasks.  
It is a system that accumulates continuity.

---

## What KMBL Is Not

KMBL is not:
- a task queue
- an agent control panel
- a static profile generator
- a chatbot interface
- a workflow approval system

---

## Core Principles

- Identity is evolving, not fixed  
- Continuity matters more than isolated outputs  
- Internal state is fluid and revisable  
- Publication is the only hard boundary  
- Agents are internal faculties expressed through the runtime, not separate entities

---

## Architecture Philosophy

- KMBL owns meaning, state, and identity  
- KMBL orchestrates execution through external role workers  
- Agents are implementation details  
- The product should feel alive, not managed

---

## Product Goal

KMBL should feel like:

- something thinking
- something evolving
- something shaping itself over time

Not:

- something waiting for instructions
- something processing tickets

---

## Execution Model

KMBL operates as a **stateful orchestration system**.

- KMBL owns state, continuity, and canon
- Execution roles may run in external systems
- Agent roles are not tied to a specific runtime location

In the current architecture:

- Planner, Generator, and Evaluator roles may be executed via an external system (e.g. KiloClaw)
- KMBL remains the control plane:
  - thread lifecycle
  - state authority
  - checkpointing
  - iteration control
  - publication

Execution is distributed.
Authority is centralized.

---

## Runtime Orientation

KMBL evolves through a stateful runtime.

It maintains continuity through:
- graph state
- threads
- checkpoints
- memory
- mutable habitat state

Its published snapshots are separate from runtime persistence.

Runtime continuity supports evolution.
Snapshots preserve canon.