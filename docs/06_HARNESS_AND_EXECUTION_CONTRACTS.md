# Harness and Execution Contracts

## Overview

This document defines execution contracts for the KMBL harness.

It describes how roles are invoked,
how state flows,
and how decisions are made.

---

## Core Principle

KMBL decides:

- when execution occurs
- which role runs
- what state is read
- what state is written
- whether execution continues or pauses

Agents:
- execute scoped work
- return structured outputs
- do not control flow

---

## Role Invocation Contracts

### Planner Contract

Input:
- prompt or event
- thread context
- identity + memory

Output:
- build_spec
- constraints
- success_criteria
- evaluation_targets

---

### Generator Contract

Input:
- build_spec
- current system state
- evaluator feedback (optional)

Output:
- proposed_changes
- artifact_outputs
- updated_state

---

### Evaluator Contract

Input:
- system output
- success_criteria
- evaluation_targets

Output:
- evaluation_report
- issues[]
- status (pass | fail | partial)

---

## KiloClaw Execution Contract

KiloClaw acts as a role execution layer.

KMBL sends:
- role identifier (planner | generator | evaluator)
- structured input payload

KiloClaw returns:
- structured output payload
- artifacts
- logs (optional)

KMBL:
- validates
- stores
- routes next step

---

## Iteration Contract

After evaluation:

- pass → eligible for publication review
- partial/fail → generator re-invoked with feedback
- blocked → interrupt

---

## Interrupt Contract

Interrupts occur when:

- human input is required
- ambiguity cannot be resolved
- approval is needed

Execution resumes on the same thread.

---

## Context Compaction Contract

Before each role invocation:

- thread state may be compacted
- irrelevant data removed
- critical signals preserved

Compaction ensures scalability without losing continuity.

---

## Checkpoint Contract

The system must checkpoint:

- before role invocation
- after role completion
- before interrupts

Checkpoints enable:
- resume
- replay
- recovery

---

## Sandbox Execution Contract

Generator outputs must be applied to an isolated environment.

This environment:
- represents a candidate build
- may be a branch, worktree, or container
- must be testable by evaluator

---

## Evaluation Contract

Evaluator must:

- review full system output
- validate against criteria
- return structured issues

Evaluation is holistic, not partial.

---

## Publication Contract

Publication is explicit.

Requirements:
- evaluator status = pass
- optional human approval

Publication creates:
- immutable snapshot

Snapshots are the only canon.

---

## State Authority Rule

KMBL determines:

- what becomes working state
- what becomes thread state
- what becomes memory
- what becomes snapshot

Agents suggest.
KMBL decides.