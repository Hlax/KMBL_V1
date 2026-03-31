# Durable graph run execution

## Current behavior (v1)

`POST /orchestrator/runs/start` persists `thread` and `graph_run`, then schedules `run_graph` via **FastAPI `BackgroundTasks`**.

- Runs **in the same process** as the API worker.
- If the process exits (deploy, crash, OOM), **in-flight work is lost** unless an external reconciler marks stale `running` rows failed (see `ORCHESTRATOR_RUNNING_STALE_AFTER_SECONDS`).
- This is appropriate for **development** and **single-node** deployments where short runs are acceptable.

## Configuration

| Env | Meaning |
|-----|---------|
| `ORCHESTRATOR_GRAPH_RUN_DISPATCH` | `fastapi_background` (default): enqueue in-process. `external_worker` is reserved for a future out-of-process consumer. |

## Production pattern

For customer-facing or long-running graphs:

1. **Queue** — enqueue a job record (`graph_run_id`, lease, attempt) in Postgres, Redis, SQS, etc.
2. **Worker** — a separate process polls the queue, calls `run_graph` with the same IDs, extends leases, retries with backoff.
3. **API** — `POST /runs/start` only inserts rows and enqueues; returns `202` + job id (optional API change).
4. **Idempotency** — workers must tolerate duplicate delivery; `persist_graph_run_start` + idempotent role saves already lean this direction.

The orchestrator’s **domain model** (thread, graph_run, checkpoints, role_invocation) is compatible with this split; only the **dispatch boundary** moves out of `BackgroundTasks`.

## Related

- [16_DEPLOYMENT_ARCHITECTURE.md](16_DEPLOYMENT_ARCHITECTURE.md) — VPS + control plane layout.
- [services/orchestrator/DEPLOY.md](../services/orchestrator/DEPLOY.md) — systemd and reverse proxy.
