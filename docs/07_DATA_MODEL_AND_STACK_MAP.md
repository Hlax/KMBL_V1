# Data Model and Stack Map

## Purpose

Define the first implementation-ready schema and stack map for KMBL under the harness architecture.

This document assumes:

- KMBL is the control plane
- Python + LangGraph orchestrate runtime execution
- KiloClaw hosts three distinct role configurations:
  - Planner
  - Generator
  - Evaluator
- Supabase/Postgres stores system state
- publication remains the only canon boundary

---

## System Roles

### KMBL

KMBL owns:

- thread continuity
- checkpoints
- graph routing
- context compaction
- role invocation records
- build records
- review surfaces
- staging snapshots
- publication snapshots

### KiloClaw

KiloClaw owns role execution for:

- Planner
- Generator
- Evaluator

KiloClaw may use:

- MCP tools
- repo access
- browser automation
- build/test commands
- sandbox workspaces

### Supabase / Postgres

Supabase stores:

- identity inputs
- thread state
- checkpoints
- run history
- role invocations
- planner outputs
- generator outputs
- evaluator outputs
- staging review records
- publication snapshots

---

# 1. Core Data Model

## 1.1 identity_source

Raw identity material provided to the system.

### Purpose

Stores uploaded or referenced identity inputs before they are synthesized.

### Fields

- `identity_source_id` uuid primary key
- `identity_id` uuid not null
- `source_type` text not null
- `source_uri` text null
- `raw_text` text null
- `metadata_json` jsonb not null default '{}'
- `created_at` timestamptz not null default now()

### Notes

`source_type` examples:

- `file`
- `url`
- `text`
- `image`
- `note`

---

## 1.2 identity_profile

Current working synthesis for an identity.

### Purpose

Stores the latest mutable identity interpretation used during planning and generation.

### Fields

- `identity_id` uuid primary key
- `profile_summary` text null
- `facets_json` jsonb not null default '{}'
- `open_questions_json` jsonb not null default '[]'
- `updated_at` timestamptz not null default now()

---

## 1.3 identity_memory

Durable memory records tied to identity.

### Purpose

Separates candidate memory from accepted memory.

### Fields

- `identity_memory_id` uuid primary key
- `identity_id` uuid not null
- `memory_type` text not null
- `content` text not null
- `confidence` numeric null
- `source_refs_json` jsonb not null default '[]'
- `created_at` timestamptz not null default now()

### Notes

`memory_type` examples:

- `candidate`
- `accepted`

---

## 1.4 thread

Continuity container for runtime execution.

### Purpose

Represents a long-lived execution context across prompts, iterations, interrupts, and resume.

### Fields

- `thread_id` uuid primary key
- `identity_id` uuid null
- `thread_kind` text not null
- `status` text not null
- `current_checkpoint_id` uuid null
- `created_at` timestamptz not null default now()
- `updated_at` timestamptz not null default now()

### Notes

`thread_kind` examples:

- `build`
- `identity`
- `review`
- `mixed`

`status` examples:

- `active`
- `paused`
- `completed`
- `archived`

---

## 1.5 checkpoint

Saved runtime state within a thread.

### Purpose

Supports resume, replay, recovery, and inspection.

### Fields

- `checkpoint_id` uuid primary key
- `thread_id` uuid not null
- `checkpoint_kind` text not null
- `state_json` jsonb not null
- `context_compaction_json` jsonb null
- `created_at` timestamptz not null default now()

### Notes

`checkpoint_kind` examples:

- `pre_role`
- `post_role`
- `interrupt`
- `manual`

---

## 1.6 graph_run

One KMBL runtime pass over a thread.

### Purpose

Represents a top-level orchestration run that may contain multiple role invocations.

### Fields

- `graph_run_id` uuid primary key
- `thread_id` uuid not null
- `trigger_type` text not null
- `status` text not null
- `started_at` timestamptz not null default now()
- `ended_at` timestamptz null

### Notes

`trigger_type` examples:

- `prompt`
- `resume`
- `schedule`
- `system`

`status` examples:

- `running`
- `paused`
- `completed`
- `failed`

---

## 1.7 role_invocation

One Planner / Generator / Evaluator call.

### Purpose

Creates the exact execution boundary between KMBL and KiloClaw.

### Fields

- `role_invocation_id` uuid primary key
- `graph_run_id` uuid not null
- `thread_id` uuid not null
- `role_type` text not null
- `provider` text not null
- `provider_config_key` text not null
- `input_payload_json` jsonb not null
- `output_payload_json` jsonb null
- `status` text not null
- `iteration_index` integer not null default 0
- `started_at` timestamptz not null default now()
- `ended_at` timestamptz null

### Notes

`role_type` values:

- `planner`
- `generator`
- `evaluator`

`provider` initial value:

- `kiloclaw`

`status` examples:

- `queued`
- `running`
- `completed`
- `failed`

---

## 1.8 build_spec

Planner output record.

### Purpose

Stores the structured build plan used by Generator.

### Fields

- `build_spec_id` uuid primary key
- `thread_id` uuid not null
- `graph_run_id` uuid not null
- `planner_invocation_id` uuid not null
- `spec_json` jsonb not null
- `constraints_json` jsonb not null default '{}'
- `success_criteria_json` jsonb not null default '[]'
- `evaluation_targets_json` jsonb not null default '[]'
- `status` text not null
- `created_at` timestamptz not null default now()

### Notes

`status` examples:

- `active`
- `superseded`
- `accepted`

---

## 1.9 build_candidate

Generator-produced candidate build.

### Purpose

Stores a reviewable candidate produced from a build spec.

### Fields

- `build_candidate_id` uuid primary key
- `thread_id` uuid not null
- `graph_run_id` uuid not null
- `generator_invocation_id` uuid not null
- `build_spec_id` uuid not null
- `candidate_kind` text not null
- `working_state_patch_json` jsonb not null default '{}'
- `artifact_refs_json` jsonb not null default '[]'
- `sandbox_ref` text null
- `preview_url` text null
- `status` text not null
- `created_at` timestamptz not null default now()

### Notes

`candidate_kind` examples:

- `habitat`
- `content`
- `full_app`

`status` examples:

- `generated`
- `applied`
- `under_review`
- `superseded`
- `accepted`

---

## 1.10 evaluation_report

Evaluator output.

### Purpose

Stores structured evaluation results that drive iteration or approval.

### Fields

- `evaluation_report_id` uuid primary key
- `thread_id` uuid not null
- `graph_run_id` uuid not null
- `evaluator_invocation_id` uuid not null
- `build_candidate_id` uuid not null
- `status` text not null
- `summary` text null
- `issues_json` jsonb not null default '[]'
- `metrics_json` jsonb not null default '{}'
- `artifacts_json` jsonb not null default '[]'
- `created_at` timestamptz not null default now()

### Notes

`status` values:

- `pass`
- `partial`
- `fail`
- `blocked`

---

## 1.11 staging_snapshot

Stable review surface built from runtime outputs.

### Purpose

Represents the review-ready staging object inside KMBL.

### Fields

- `staging_snapshot_id` uuid primary key
- `thread_id` uuid not null
- `build_candidate_id` uuid not null
- `identity_id` uuid null
- `snapshot_payload_json` jsonb not null
- `preview_url` text null
- `status` text not null
- `created_at` timestamptz not null default now()

### Notes

`status` examples:

- `draft`
- `review_ready`
- `approved`
- `rejected`

---

## 1.12 publication_snapshot

Immutable canon/public state.

### Purpose

Represents the only canonical published record.

### Fields

- `publication_snapshot_id` uuid primary key
- `identity_id` uuid null
- `source_staging_snapshot_id` uuid not null
- `payload_json` jsonb not null
- `published_at` timestamptz not null default now()
- `published_by` text null
- `visibility` text not null default 'private'
- `parent_snapshot_id` uuid null

### Notes

`visibility` values:

- `private`
- `public`

---

# 2. Relationships

## Identity Layer

- `identity_source.identity_id` → `identity_profile.identity_id`
- `identity_memory.identity_id` → `identity_profile.identity_id`
- `thread.identity_id` → `identity_profile.identity_id`

## Runtime Layer

- `checkpoint.thread_id` → `thread.thread_id`
- `graph_run.thread_id` → `thread.thread_id`
- `role_invocation.graph_run_id` → `graph_run.graph_run_id`
- `role_invocation.thread_id` → `thread.thread_id`

## Build Layer

- `build_spec.thread_id` → `thread.thread_id`
- `build_spec.graph_run_id` → `graph_run.graph_run_id`
- `build_spec.planner_invocation_id` → `role_invocation.role_invocation_id`

- `build_candidate.thread_id` → `thread.thread_id`
- `build_candidate.graph_run_id` → `graph_run.graph_run_id`
- `build_candidate.generator_invocation_id` → `role_invocation.role_invocation_id`
- `build_candidate.build_spec_id` → `build_spec.build_spec_id`

- `evaluation_report.thread_id` → `thread.thread_id`
- `evaluation_report.graph_run_id` → `graph_run.graph_run_id`
- `evaluation_report.evaluator_invocation_id` → `role_invocation.role_invocation_id`
- `evaluation_report.build_candidate_id` → `build_candidate.build_candidate_id`

## Snapshot Layer

- `staging_snapshot.thread_id` → `thread.thread_id`
- `staging_snapshot.build_candidate_id` → `build_candidate.build_candidate_id`

- `publication_snapshot.source_staging_snapshot_id` → `staging_snapshot.staging_snapshot_id`
- `publication_snapshot.parent_snapshot_id` → `publication_snapshot.publication_snapshot_id`

---

# 3. State Ownership

## KMBL owns

- identity sources
- identity profile
- identity memory
- threads
- checkpoints
- graph runs
- role invocations
- build specs
- build candidates
- evaluation reports
- staging snapshots
- publication snapshots

## KiloClaw owns temporarily

- role-local execution context
- MCP usage
- repo operations
- browser/test operations
- raw worker internals

KMBL persists the normalized outputs it cares about.

---

# 4. Role Payload Contracts

## 4.1 Planner Request

'''json
{
  "thread_id": "uuid",
  "identity_context": {},
  "memory_context": {},
  "event_input": {},
  "current_state_summary": {}
}
'''

## 4.2 Planner Response

'''json
{
  "build_spec": {},
  "constraints": {},
  "success_criteria": [],
  "evaluation_targets": []
}
'''

## 4.3 Generator Request

'''json
{
  "thread_id": "uuid",
  "build_spec": {},
  "current_working_state": {},
  "iteration_feedback": null
}
'''

## 4.4 Generator Response

'''json
{
  "proposed_changes": {},
  "artifact_outputs": [],
  "updated_state": {},
  "sandbox_ref": "string",
  "preview_url": "string"
}
'''

## 4.5 Evaluator Request

'''json
{
  "thread_id": "uuid",
  "build_candidate": {},
  "success_criteria": [],
  "evaluation_targets": []
}
'''

## 4.6 Evaluator Response

'''json
{
  "status": "pass",
  "summary": "string",
  "issues": [],
  "artifacts": [],
  "metrics": {}
}
'''

---

# 5. Stack Map

## Overview

KMBL is composed of four primary layers:

1. App Layer (UI + API)
2. Orchestrator Layer (LangGraph runtime)
3. Data Layer (state + persistence)
4. Role Execution Layer (KiloClaw)
5. Sandbox / Preview Layer (build + evaluation target)

Each layer has a clear responsibility boundary.

---

## 5.1 KMBL App Layer

### Stack

- Next.js
- React
- TypeScript

### Responsibilities

- operator interface
- identity source upload + review
- staging snapshot rendering
- evaluation report display
- publication controls
- preview embedding
- orchestration API endpoints

### Key Principle

The app does not build.

It:
- displays
- triggers
- reviews
- approves

---

## 5.2 KMBL Orchestrator Layer

### Stack

- Python
- LangGraph

### Responsibilities

- thread resolution
- checkpointing
- context hydration
- context compaction
- role routing
- iteration loop
- interrupt handling
- persistence writes

### Key Principle

This is the system brain.

It:
- decides what runs
- decides when to loop
- decides when to stop

---

## 5.3 Data Layer

### Stack

- Supabase
- Postgres
- Storage (for files/artifacts)

### Responsibilities

- all persistent records
- thread + checkpoint storage
- run history
- role invocation logs
- build artifacts
- evaluation results
- staging + publication snapshots
- identity + memory

### Key Principle

KMBL is the system of record.

Nothing important should only exist inside KiloClaw.

---

## 5.4 Role Execution Layer (KiloClaw)

### Configuration

KiloClaw hosts three distinct configurations:

- Planner
- Generator
- Evaluator

### Responsibilities

- role execution
- MCP/tool access
- repo edits
- browser automation
- test/build commands
- artifact generation

### Key Principle

KiloClaw executes work.

KMBL decides when and why.

---

## 5.5 Sandbox / Preview Layer

### v1 Implementation Options

- git worktree
- isolated branch workspace
- temporary preview deployment
- local or remote build target

### Responsibilities

- host candidate build output
- provide preview URL
- serve as evaluator test target

### Key Principle

Every generator output must be testable.

If it cannot be evaluated, it is not a valid build.

---

# 6. Runtime Sequence

## Standard Flow

1. Event enters KMBL

- user prompt
- identity update
- resume request

---

2. Thread Resolution

- find existing thread or create new

---

3. Context Hydration

- load thread state
- load identity + memory
- apply compaction

---

4. Checkpoint (pre-execution)

- persist current state

---

5. Planner Invocation

KMBL → KiloClaw (Planner)

Result:
- build_spec
- success_criteria
- evaluation_targets

Store:
→ `build_spec`

---

6. Generator Invocation

KMBL → KiloClaw (Generator)

Result:
- proposed_changes
- artifact_outputs
- updated_state
- sandbox_ref
- preview_url

Store:
→ `build_candidate`

---

7. Evaluator Invocation

KMBL → KiloClaw (Evaluator)

Result:
- status
- issues
- summary
- metrics

Store:
→ `evaluation_report`

---

8. Decision Step

Based on evaluation:

### pass
→ create staging snapshot
→ wait for publication

### partial / fail
→ re-invoke Generator with feedback

### blocked
→ interrupt

---

9. Iteration Loop

Generator receives:

- prior build_spec
- evaluation feedback
- current working state

Repeat:
Generator → Evaluator → Decision

---

10. Staging Snapshot

KMBL constructs:

- reviewable payload
- preview surface
- UI rendering

Store:
→ `staging_snapshot`

---

11. Publication

Manual or gated action:

- snapshot validated
- optional human approval

Create:
→ `publication_snapshot`

This is immutable.

---

# 7. Minimal v1 Build Order

## Phase 1 — Schema

Create tables:

- thread
- checkpoint
- graph_run
- role_invocation
- build_spec
- build_candidate
- evaluation_report
- staging_snapshot
- publication_snapshot

---

## Phase 2 — Orchestrator

Build minimal LangGraph flow:

- resolve thread
- checkpoint
- call planner
- call generator
- call evaluator
- decision router

No UI complexity yet.

---

## Phase 3 — KiloClaw Setup

Create and test:

- Planner config
- Generator config
- Evaluator config

Validate each independently.

---

## Phase 4 — First End-to-End Loop

Run one simple scenario:

- identity input
- planner output
- generator candidate
- evaluator report
- staging snapshot

No iteration needed yet.

---

## Phase 5 — Iteration Loop

Enable:

- evaluator feedback → generator
- multiple passes
- iteration tracking

---

## Phase 6 — Review + Publish

Add:

- staging UI
- evaluation UI
- publish action
- snapshot creation

---

# 8. Design Rules

## Rule 1

KiloClaw executes.

KMBL orchestrates.

---

## Rule 2

Runtime outputs are not canon.

---

## Rule 3

Only publication creates immutable truth.

---

## Rule 4

Threads preserve continuity.

---

## Rule 5

Checkpoints enable resume and recovery.

---

## Rule 6

Evaluation controls iteration.

It does not automatically publish.

---

# 9. Practical First Target

Your first working version should be:

- one identity source
- one planner spec
- one generator output
- one evaluator report
- one staging snapshot

No fancy UI.
No complex memory.
No full app generation.

Just prove:

→ the loop works
→ the data is stored
→ the system can iterate

Everything else builds from that.
