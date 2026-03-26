# API and Service Layer

## Purpose

Define how the KMBL app layer talks to:

- the Python/LangGraph orchestrator
- Supabase/Postgres
- KiloClaw role workers
- sandbox / preview services

This document specifies:

- service boundaries
- API responsibilities
- request flow
- minimal v1 endpoints

---

## Core Principle

The app layer triggers and displays.

The orchestrator decides.

KiloClaw executes.

The database persists.

---

# 1. Service Boundaries

## 1.1 App Layer

The Next.js app is responsible for:

- operator actions
- file upload
- review surfaces
- publication actions
- API request entrypoints

It should not contain orchestration logic.

---

## 1.2 Orchestrator Layer

The Python/LangGraph service is responsible for:

- thread resolution
- state hydration
- checkpointing
- role routing
- iteration logic
- interrupt handling
- persistence coordination

It is the execution brain of KMBL.

---

## 1.3 Role Execution Layer

KiloClaw is responsible for:

- Planner execution
- Generator execution
- Evaluator execution
- tool access
- repo operations
- sandbox interactions

It receives structured payloads and returns structured outputs.

---

## 1.4 Data Layer

Supabase/Postgres is responsible for:

- durable state
- run history
- role invocation history
- build records
- snapshots
- identity records

---

# 2. High-Level Request Flow

## Standard Build Request

1. app sends request to orchestrator
2. orchestrator resolves thread
3. orchestrator loads context
4. orchestrator invokes Planner via KiloClaw
5. orchestrator invokes Generator via KiloClaw
6. orchestrator invokes Evaluator via KiloClaw
7. orchestrator stores outputs
8. orchestrator returns run status to app
9. app renders review surfaces from persisted records

---

# 3. API Shape

## Design Rule

The app should talk to KMBL services, not directly to KiloClaw.

This preserves:

- centralized authority
- logging
- validation
- future flexibility

---

# 4. App API Endpoints

## 4.1 Identity Source Upload

### Route

`POST /api/identity/sources`

### Purpose

Create identity source records and upload associated material.

### Request

'''json
{
  "identity_id": "uuid",
  "source_type": "text",
  "raw_text": "..."
}
'''

### Response

'''json
{
  "identity_source_id": "uuid",
  "status": "created"
}
'''

---

## 4.2 Start Build Run

### Route

`POST /api/runs`

### Purpose

Start a new graph run.

### Request

'''json
{
  "thread_id": null,
  "identity_id": "uuid",
  "trigger_type": "prompt",
  "event_input": {
    "prompt": "Build the first habitat candidate"
  }
}
'''

### Response

'''json
{
  "graph_run_id": "uuid",
  "thread_id": "uuid",
  "status": "started"
}
'''

---

## 4.3 Resume Run

### Route

`POST /api/runs/{graph_run_id}/resume`

### Purpose

Resume interrupted execution.

### Request

'''json
{
  "resume_input": {}
}
'''

### Response

'''json
{
  "graph_run_id": "uuid",
  "status": "resumed"
}
'''

---

## 4.4 Get Run Status

### Route

`GET /api/runs/{graph_run_id}`

### Purpose

Fetch current run state.

### Response

'''json
{
  "graph_run_id": "uuid",
  "thread_id": "uuid",
  "status": "running",
  "iteration_index": 1,
  "decision": null
}
'''

---

## 4.5 Get Staging Snapshot

### Route

`GET /api/staging/{staging_snapshot_id}`

### Purpose

Fetch review-ready staging payload.

### Response

'''json
{
  "staging_snapshot_id": "uuid",
  "status": "review_ready",
  "snapshot_payload": {},
  "preview_url": "https://..."
}
'''

---

## 4.6 Publish Snapshot

### Route

`POST /api/publication`

### Purpose

Create immutable publication snapshot from approved staging snapshot.

### Request

'''json
{
  "staging_snapshot_id": "uuid",
  "visibility": "public"
}
'''

### Response

'''json
{
  "publication_snapshot_id": "uuid",
  "status": "published"
}
'''

---

# 5. Orchestrator Service Endpoints

These endpoints are internal-facing.

The app may call them through server-side handlers.

---

## 5.1 Start Orchestration

### Route

`POST /orchestrator/runs/start`

### Purpose

Create or continue a thread and begin graph execution.

### Request

'''json
{
  "identity_id": "uuid",
  "thread_id": null,
  "trigger_type": "prompt",
  "event_input": {}
}
'''

### Response

'''json
{
  "graph_run_id": "uuid",
  "thread_id": "uuid",
  "status": "running"
}
'''

---

## 5.2 Resume Orchestration

### Route

`POST /orchestrator/runs/resume`

### Purpose

Resume from checkpoint.

### Request

'''json
{
  "thread_id": "uuid",
  "checkpoint_id": "uuid",
  "resume_input": {}
}
'''

### Response

'''json
{
  "graph_run_id": "uuid",
  "status": "running"
}
'''

---

## 5.3 Run Status

### Route

`GET /orchestrator/runs/{graph_run_id}`

### Purpose

Return execution status plus latest known records.

---

# 6. KiloClaw Invocation Service

## Role

A small service wrapper inside KMBL that calls KiloClaw consistently.

This layer should:

- choose the correct KiloClaw config
- validate payload shape
- send request
- normalize response
- capture errors
- write role_invocation records

---

## 6.1 Planner Invocation

### Input

'''json
{
  "role_type": "planner",
  "payload": {
    "thread_id": "uuid",
    "identity_context": {},
    "memory_context": {},
    "event_input": {},
    "current_state_summary": {}
  }
}
'''

---

## 6.2 Generator Invocation

### Input

'''json
{
  "role_type": "generator",
  "payload": {
    "thread_id": "uuid",
    "build_spec": {},
    "current_working_state": {},
    "iteration_feedback": {}
  }
}
'''

---

## 6.3 Evaluator Invocation

### Input

'''json
{
  "role_type": "evaluator",
  "payload": {
    "thread_id": "uuid",
    "build_candidate": {},
    "success_criteria": [],
    "evaluation_targets": []
  }
}
'''

---

# 7. Service Responsibilities by Layer

## App Layer Must

- accept user actions
- upload files
- trigger runs
- fetch status
- display staging
- display evaluation results
- trigger publication

## App Layer Must Not

- call KiloClaw directly
- decide iteration
- mutate thread state directly

---

## Orchestrator Must

- own graph execution
- own thread continuity
- own checkpoints
- own iteration decisions
- persist meaningful outputs

## Orchestrator Must Not

- render UI
- expose raw KiloClaw responses without normalization

---

## KiloClaw Wrapper Must

- select Planner / Generator / Evaluator config
- validate payloads
- normalize outputs
- report failures cleanly

---

# 8. Minimal v1 Endpoint Set

Start with only these:

- `POST /api/identity/sources`
- `POST /api/runs`
- `GET /api/runs/{graph_run_id}`
- `GET /api/staging/{staging_snapshot_id}`
- `POST /api/publication`

Internal:

- `POST /orchestrator/runs/start`
- `POST /orchestrator/invoke-role`

Skip everything else initially.

---

# 9. Error Handling

## App-Level Errors

Return:

- validation errors
- missing record errors
- unauthorized actions
- publication eligibility failures

---

## Orchestrator Errors

Return:

- run start failure
- checkpoint failure
- role invocation failure
- iteration exhaustion
- interrupt required

---

## KiloClaw Invocation Errors

Return normalized structure:

'''json
{
  "status": "failed",
  "error_type": "provider_error",
  "message": "..."
}
'''

Do not expose raw provider formatting directly as product truth.

---

# 10. Webhook Support (Optional)

If KiloClaw role execution becomes asynchronous later, add:

- `POST /api/webhooks/kiloclaw`

Purpose:

- receive completion callback
- update role_invocation
- resume orchestrator if needed

Not required for synchronous v1.

---

# 11. Security Rules

- app clients do not receive direct KiloClaw credentials
- orchestrator secrets stay server-side
- publication endpoints require explicit authorization
- sandbox operations must remain isolated per run

---

# 12. Minimal v1 Build Sequence

1. implement identity upload endpoint
2. implement run start endpoint
3. implement internal orchestrator start endpoint
4. implement internal KiloClaw invoke-role wrapper
5. implement run status endpoint
6. implement staging fetch endpoint
7. implement publication endpoint

---

# 13. Design Rules

## Rule 1

The app talks to KMBL services.

Not directly to KiloClaw.

---

## Rule 2

The orchestrator is the only execution authority.

---

## Rule 3

KiloClaw responses must be normalized before becoming product records.

---

## Rule 4

Publication must remain explicit.

---

## Rule 5

Review surfaces should read from persisted records, not transient runtime memory.

---

# 14. Future Extensions

- streaming run status
- live event timeline
- webhook-driven long-running roles
- richer review APIs
- audit/event service
- multi-sandbox status endpoints

Not required for v1.