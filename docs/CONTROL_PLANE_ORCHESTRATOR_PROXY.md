# Control plane → orchestrator proxy behavior

Next.js API routes under `apps/control-plane/app/api/` forward to the Python orchestrator using a **single resolved base URL** on the server. Resolution order (see [`orchestrator-server-origin.ts`](../apps/control-plane/lib/orchestrator-server-origin.ts)):

1. **`NEXT_PUBLIC_ORCHESTRATOR_URL`** (trimmed, no trailing slash) — primary; use this in `.env.local` for local and in Vercel env for production.
2. **`ORCHESTRATOR_ORIGIN`** — legacy fallback when (1) is unset (older setups).
3. **`http://127.0.0.1:8010`** — local default.

**Why this matters:** Previously, `POST /api/runs/start` used only `ORCHESTRATOR_ORIGIN` with a localhost default, while most other routes used `NEXT_PUBLIC_ORCHESTRATOR_URL`. If you pointed the app at a **remote** orchestrator via `NEXT_PUBLIC_ORCHESTRATOR_URL` but left `ORCHESTRATOR_ORIGIN` unset, **run start** could still call **localhost**, hitting a different (often stale) Python process — for example old behavior such as `409` with `active_status: interrupt_requested` after the server was fixed. Keep **one** orchestrator URL in `NEXT_PUBLIC_ORCHESTRATOR_URL` so every proxy agrees.

When the upstream returns FastAPI’s route miss (`404` with `{"detail":"Not Found"}`), helpers in [`orchestrator-proxy.ts`](../apps/control-plane/lib/orchestrator-proxy.ts) return **synthetic JSON** with `backend_unimplemented: true`.

## Live habitat (`/habitat/live/{thread_id}`)

- The path parameter is **`thread_id`**, not `graph_run_id`. Use the thread id from graph run detail (`summary.thread_id`).
- Orchestrator `GET /orchestrator/working-staging/{thread_id}/live` returns **404** when there is no `working_staging` row for that thread. That is normal if a run **failed before the staging node** persisted working staging (see LangGraph flow: staging runs only after a **stage** decision).
- Error bodies use FastAPI’s **`detail`** field; the control plane maps that to the UI (see [`orchestrator-error-message.ts`](../apps/control-plane/lib/orchestrator-error-message.ts)).
- `GET /orchestrator/runs/{id}/detail` includes **`working_staging_present`** on the summary when the orchestrator supports it, so operators can see whether live habitat will succeed before opening the page.

## Fail-open routes (200 + fallback body)

| Route | Fallback helper | Risk |
|-------|-----------------|------|
| `GET /api/runs` | `fallbackRunsList` | Empty list; looks idle |
| `GET /api/runs/[graphRunId]` | `fallbackGraphRunDetail` | Fake minimal run detail |
| `GET /api/operator-summary` | `fallbackOperatorSummary` | Zeroed metrics |
| `GET /api/proposals` | `fallbackProposals` | Empty proposals |
| `GET /api/publication` | `fallbackPublicationList` | Empty list |
| `GET /api/publication/current` | `fallbackPublicationCurrent` | Null canon |
| `GET /api/staging` | `fallbackStagingList` | Empty staging |

These are **fail-open by design** for local dev when the orchestrator binary or URL is wrong. Production operators should set `NEXT_PUBLIC_ORCHESTRATOR_URL` correctly and treat `backend_unimplemented: true` in JSON as **upstream missing**, not empty data.

## Fail-closed / truth surfaces

- `GET /api/orchestrator-health` — proxies orchestrator `GET /health` without synthetic success bodies; exposes transport resolution when the orchestrator is reachable.
- `GET /api/system-mode` — derives **`fully_connected` | `degraded` | `fallback`** from orchestrator `/health` plus **two** probes of the runs list surface:
  - **Direct:** `GET {NEXT_PUBLIC_ORCHESTRATOR_URL}/orchestrator/runs?limit=1` from the control-plane server (validates the orchestrator binary and route, independent of Next routing).
  - **Proxied:** same-origin `GET /api/runs?limit=1` (validates the browser-facing proxy path and env on the server). Split deployments (CP and orchestrator on different hosts) are not fully covered by same-origin alone; the direct probe closes that gap. See [`system-mode.ts`](../apps/control-plane/lib/system-mode.ts).
- UI: [`OrchestratorTruthBanner`](../apps/control-plane/app/components/OrchestratorTruthBanner.tsx) shows system mode (not visually equivalent to “healthy” when degraded or fallback) and stub-transport warnings when `kiloclaw_resolution` reports stub mode.

## System modes

| Mode | Meaning |
|------|---------|
| **fully_connected** | Orchestrator URL set, `/health` OK, transport config valid, **direct** `GET /orchestrator/runs` healthy, **and** same-origin `GET /api/runs` OK without synthetic fallback. |
| **degraded** | URL unset, orchestrator unreachable, KiloClaw transport misconfigured, **direct** runs list probe failed, or **proxy** `/api/runs` non-OK (e.g. 502 / env missing on server). |
| **fallback** | Same-origin `/api/runs` returned **200** with `backend_unimplemented: true` (synthetic empty list). Checked **after** proxy response OK so 502/500 stay **degraded**. |

## Detection

`isOrchestratorRouteNotFound` distinguishes FastAPI “no route” from resource-level 404s (e.g. graph run not found).
`evaluateRunsListProbe` classifies both direct and proxied `/orchestrator/runs` responses (JSON parse, route miss, `backend_unimplemented`).
