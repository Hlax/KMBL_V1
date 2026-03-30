# KiloClaw sync adapter (VPS) — architecture for KMBL `http` transport

## Problem statement

OpenClaw’s HTTP surface for role work is typically:

- **`POST /hooks/agent`** — accepts a run, returns **`{ ok, runId }`** immediately. **Role output is not in the HTTP response** (async delivery to sessions/channels).

KMBL’s LangGraph expects **synchronous** role invocation: one HTTP round-trip must yield **structured planner / generator / evaluator JSON** so the next node can run. **KMBL v1 does not redesign** around async jobs + polling in the orchestrator.

Therefore: **something on the execution side** must turn “invoke agent” into a **blocking** call that returns **final JSON**.

## Recommended architecture (best practice for this repo)

**Deploy `services/openclaw-sync-proxy` on the same VPS as OpenClaw/KiloClaw** (same host where the `openclaw` CLI works).

| Layer | Role |
|--------|------|
| **KMBL orchestrator** (anywhere) | `KILOCLAW_TRANSPORT=http`, `POST {KILOCLAW_BASE_URL}/v1/invoke` with KMBL body + Bearer token |
| **sync proxy** (VPS) | Accepts KMBL contract, runs **`openclaw agent --agent <config_key> --message '<json>' --json`**, parses stdout, returns `{ "output": <role-shaped dict> }` |
| **OpenClaw gateway** (`localhost:3001`) | Unchanged; **not** used for `/hooks/agent` on the KMBL critical path |

**Why not “adapter over `/hooks/agent` only”?**

Without a **documented, reliable** “get result by `runId`” HTTP API, you cannot poll to completion. Webhooks + KMBL callback would require **async orchestration** and public callback URLs — **out of scope for v1**. The **CLI on the VPS** is the smallest mechanism that **blocks until the agent finishes** and returns JSON on stdout.

**Why not a Node-specific service?**

The repo already ships a **minimal FastAPI** proxy (`openclaw-sync-proxy`). Node is optional; **same process model** (thin HTTP + subprocess) is what matters.

**Why not “a route inside KiloClaw” only if you fork it?**

If your product can add **`POST /v1/invoke`** upstream with the same semantics as this proxy, that is ideal long-term. Until then, **run the proxy alongside** the gateway.

## Exact request/response contract (KMBL ↔ sync proxy)

**Request** — matches `KiloClawHttpClient` in `services/orchestrator`:

- `POST /v1/invoke`
- `Authorization: Bearer <shared secret>`
- `Content-Type: application/json`

```json
{
  "role_type": "planner",
  "config_key": "kmbl-planner",
  "payload": { }
}
```

`config_key` **is** the OpenClaw `agentId` (e.g. `kmbl-planner`). `payload` is the same object KMBL builds in the graph (planner/generator/evaluator shapes).

**Response** (success):

```json
{
  "output": {
    "build_spec": {},
    "constraints": {},
    "success_criteria": [],
    "evaluation_targets": []
  }
}
```

(Shape varies by role; planner example shown.)

The orchestrator unwraps `output` / `result` / OpenClaw CLI envelopes via `_extract_http_role_dict` in `providers/kiloclaw.py`.

## Result collection strategy (inside the proxy)

1. **Serialize** `payload` to a JSON string → `openclaw agent --message <json>`.
2. **Run subprocess** with timeout; **wait** for process exit.
3. **Parse** stdout JSON; **extract** role-shaped object from `result.payloads[0].text` or top-level (same heuristics as KMBL’s `extract_role_payload_from_openclaw_output`).
4. Return `{ "output": role }`.

**No** `/hooks/agent` in this path unless you later add a **pollable** result API.

## Timeout and error behavior

| Case | Behavior |
|------|----------|
| Subprocess exceeds `OPENCLAW_TIMEOUT_SEC` | HTTP **504** from proxy |
| Non-zero `openclaw` exit | **502** + stderr preview |
| stdout not valid JSON / no role shape | **502** with message |
| Missing/invalid Bearer token | **401** / **500** (if token not configured on proxy) |

KMBL maps HTTP ≥400 and parse failures to `KiloClawInvocationError` → failed `role_invocation`.

## Minimal implementation plan (VPS)

1. Install **`openclaw`** CLI on the VPS (same environment agents use).
2. Install **`openclaw-sync-proxy`** from this repo (`pip install -e services/openclaw-sync-proxy` or copy tree).
3. Set **`OPENCLAW_SYNC_PROXY_TOKEN`** to a long random secret; **same value** as orchestrator **`KILOCLAW_API_KEY`**.
4. Bind: **`OPENCLAW_SYNC_PROXY_HOST=0.0.0.0`**, **`OPENCLAW_SYNC_PROXY_PORT=8090`** (or behind nginx only on `127.0.0.1:8090`).
5. Expose **HTTPS** to the internet via **Tailscale Funnel**, **Cloudflare Tunnel**, or **nginx/Caddy** TLS — do **not** expose the raw OpenClaw gateway port broadly if you can avoid it; expose **only** `/v1/invoke` with auth.
6. Point **`KILOCLAW_BASE_URL`** at the **public HTTPS URL** of the proxy (no path in base URL), **`KILOCLAW_INVOKE_PATH=/v1/invoke`**, **`KILOCLAW_TRANSPORT=http`**.

## Security recommendations

- **TLS** on the public URL (tunnel or reverse proxy).
- **Bearer token** shared only between orchestrator and proxy (rotate if leaked).
- Prefer **allowlisting** orchestrator egress IPs or **Tailscale** private networking so `/v1/invoke` is not world-open.
- Rate-limit at the reverse proxy if the URL is public.

## Relationship to `POST /hooks/agent`

`/hooks/agent` remains useful for **fire-and-forget** or **UI** flows. For **KMBL graph execution**, use **sync proxy + CLI** until OpenClaw provides an official **sync invoke with body result** or a **supported poll API** for `runId`.
