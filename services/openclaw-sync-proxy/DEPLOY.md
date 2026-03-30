# openclaw-sync-proxy — deployment & runbook

This document matches the code in `src/openclaw_sync_proxy/main.py`. It does **not** use `POST /hooks/agent`; sync is **`openclaw agent --json`** on the same host.

---

## 1. Repo facts (inspection summary)

### Startup commands (pick one)

**A — uvicorn directly** (from `services/openclaw-sync-proxy` after install):

```bash
cd /path/to/KMBL_V1/services/openclaw-sync-proxy
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
export OPENCLAW_SYNC_PROXY_TOKEN="your-long-random-secret"
export OPENCLAW_SYNC_PROXY_HOST=0.0.0.0
export OPENCLAW_SYNC_PROXY_PORT=8090
python -m uvicorn openclaw_sync_proxy.main:app --host "${OPENCLAW_SYNC_PROXY_HOST}" --port "${OPENCLAW_SYNC_PROXY_PORT}"
```

**B — installed console script** (same env vars; uses `run()` in `main.py`):

```bash
pip install -e .
export OPENCLAW_SYNC_PROXY_TOKEN="your-long-random-secret"
openclaw-sync-proxy
```

Defaults inside `run()`: host `0.0.0.0`, port `8090` (overridable via env).

### Required environment variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `OPENCLAW_SYNC_PROXY_TOKEN` | **Yes** | — | Bearer token; must match orchestrator `KILOCLAW_API_KEY` exactly. |
| `OPENCLAW_SYNC_PROXY_HOST` | No | `0.0.0.0` | Bind address. |
| `OPENCLAW_SYNC_PROXY_PORT` | No | `8090` | Listen port. |
| `OPENCLAW_EXECUTABLE` | No | `openclaw` | CLI binary name or path (`which` resolved). |
| `OPENCLAW_TIMEOUT_SEC` | No | `300` | Subprocess timeout (seconds). |

### Health endpoint

- **GET** `/health`
- **No auth** (intentionally minimal; do not expose raw port to the public internet — use TLS + reverse proxy in production.)

**Example JSON:**

```json
{
  "status": "ok",
  "service": "openclaw-sync-proxy",
  "backend": "openclaw_cli_subprocess",
  "openclaw_executable": "openclaw"
}
```

### POST `/v1/invoke` — request / response

**Headers**

- `Content-Type: application/json`
- `Authorization: Bearer <OPENCLAW_SYNC_PROXY_TOKEN>`

**Body (JSON)**

```json
{
  "role_type": "planner",
  "config_key": "kmbl-planner",
  "payload": {
    "thread_id": "uuid-string",
    "identity_context": {},
    "memory_context": {},
    "event_input": { "prompt": "..." },
    "current_state_summary": {}
  }
}
```

**Success (200)** — KMBL-compatible wrapper:

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

(Exact keys inside `output` depend on role and agent; must satisfy KMBL’s `kiloclaw.py` validators.)

**Failure** — HTTP 401, 500, 502, 504 with `detail` string (FastAPI).

---

## 2. VPS deployment runbook

### Prerequisites

- **Python ≥ 3.10** on the VPS.
- **`openclaw`** CLI available on the same machine and on `PATH` (or set `OPENCLAW_EXECUTABLE` to full path). Verify:

  ```bash
  which openclaw
  openclaw agent --help
  ```

- **Agents** `kmbl-planner`, `kmbl-generator`, `kmbl-evaluator` configured in OpenClaw (same as today).

### Install sync proxy

1. Copy or clone the repo (at least `services/openclaw-sync-proxy/`).
2. Create venv, install editable:

   ```bash
   cd services/openclaw-sync-proxy
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -U pip
   pip install -e .
   ```

### Configure token

Generate a long random secret (e.g. `openssl rand -hex 32`). Set:

```bash
export OPENCLAW_SYNC_PROXY_TOKEN="<that-secret>"
```

Use the **same value** later as **`KILOCLAW_API_KEY`** in KMBL (orchestrator).

### Configure host/port

Bind on all interfaces (behind firewall / reverse proxy):

```bash
export OPENCLAW_SYNC_PROXY_HOST=0.0.0.0
export OPENCLAW_SYNC_PROXY_PORT=8090
```

Or bind **`127.0.0.1:8090`** only and let **nginx/Caddy** listen on `443` and proxy to upstream.

### HTTPS in front

**Do not** expose plain HTTP to the internet. Typical patterns:

1. **Caddy / nginx** on the VPS: TLS termination, `proxy_pass http://127.0.0.1:8090`, optional IP allowlist.
2. **Tailscale** private IP or **Tailscale Funnel** for a public HTTPS URL.
3. **Cloudflare Tunnel** (`cloudflared`) to `http://127.0.0.1:8090`.

You will use the **public HTTPS origin** (scheme + host, optional port if non-443) as **`KILOCLAW_BASE_URL`** — **no path** in the base URL.

### Verify `/health`

```bash
curl -sS "https://YOUR_PROXY_HOST/health"
```

Expect `status: ok` and `backend: openclaw_cli_subprocess`.

### Verify `/v1/invoke` (planner)

Use the curl in **section 4** below with your real `YOUR_PROXY_HOST` and `YOUR_TOKEN`.

---

## 3. KMBL orchestrator `.env.local` (after proxy is live)

Use your **public HTTPS origin** (no trailing slash) and the **same** Bearer secret as the proxy.

```env
KILOCLAW_TRANSPORT=http
KILOCLAW_BASE_URL=https://YOUR_PROXY_PUBLIC_HOST
KILOCLAW_INVOKE_PATH=/v1/invoke
KILOCLAW_API_KEY=YOUR_TOKEN_SAME_AS_OPENCLAW_SYNC_PROXY_TOKEN
KILOCLAW_PLANNER_CONFIG_KEY=kmbl-planner
KILOCLAW_GENERATOR_CONFIG_KEY=kmbl-generator
KILOCLAW_EVALUATOR_CONFIG_KEY=kmbl-evaluator
```

Optional: `KILOCLAW_BASE_URL` may include a non-default port, e.g. `https://kiloclaw.example.com:8443` if your TLS listener uses 8443.

---

## 4. Exact curl tests

Replace placeholders:

- `YOUR_PROXY_PUBLIC_HOST` — HTTPS origin only (no path).
- `YOUR_TOKEN` — same as `OPENCLAW_SYNC_PROXY_TOKEN` / `KILOCLAW_API_KEY`.

### GET `/health`

```bash
curl -sS "https://YOUR_PROXY_PUBLIC_HOST/health"
```

### POST `/v1/invoke` (planner)

```bash
curl -sS -w "\nHTTP_CODE:%{http_code}\n" -X POST "https://YOUR_PROXY_PUBLIC_HOST/v1/invoke" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "role_type": "planner",
    "config_key": "kmbl-planner",
    "payload": {
      "thread_id": "00000000-0000-0000-0000-000000000001",
      "identity_context": {},
      "memory_context": {},
      "event_input": { "prompt": "minimal planner probe from curl" },
      "current_state_summary": {}
    }
  }'
```

Expect **HTTP 200** and JSON with **`"output": { ... }`** containing at least **`build_spec`**.

---

## 5. End-to-end verification checklist (KMBL + proxy)

| # | Check | Pass criteria |
|---|--------|----------------|
| 1 | Proxy **`GET /health`** | `status` = `ok`, `backend` = `openclaw_cli_subprocess` |
| 2 | Proxy **`POST /v1/invoke`** (planner) | HTTP 200, `output.build_spec` present |
| 3 | Orchestrator **`GET /health`** | `kiloclaw_transport` = `http`, `kiloclaw_transport_effective` = `http`, `kiloclaw_base_url` is your HTTPS proxy origin, `kiloclaw_invoke_path` = `/v1/invoke`, three `kmbl-*` config keys present |
| 4 | **`POST /orchestrator/runs/start`** | HTTP 200, `status` = `completed` (or `failed` with a clear provider error if agents misbehave) |
| 5 | **`role_invocation`** rows | Three rows, `status` = `completed`, **`output_payload_json`** not stub-shaped (no `stub_spec` / `stub evaluation` if agents return real content) |
| 6 | **`build_spec` / `build_candidate` / `evaluation_report`** | Normalized columns filled; **`raw_payload_json`** populated with **real** agent JSON (not identical to stub-only values) |

If step 2 fails but `openclaw` works on the shell, check proxy logs, `OPENCLAW_EXECUTABLE`, and agent IDs.

---

## Systemd (optional)

Example unit — adjust paths and user:

```ini
[Unit]
Description=openclaw-sync-proxy for KMBL
After=network.target

[Service]
Type=simple
User=openclaw
WorkingDirectory=/opt/kmbl/KMBL_V1/services/openclaw-sync-proxy
Environment=OPENCLAW_SYNC_PROXY_TOKEN=your-token
Environment=OPENCLAW_SYNC_PROXY_HOST=127.0.0.1
Environment=OPENCLAW_SYNC_PROXY_PORT=8090
ExecStart=/opt/kmbl/KMBL_V1/services/openclaw-sync-proxy/.venv/bin/python -m uvicorn openclaw_sync_proxy.main:app --host 127.0.0.1 --port 8090
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Then enable TLS in front of `127.0.0.1:8090`.
