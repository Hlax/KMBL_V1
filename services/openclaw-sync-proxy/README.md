# openclaw-sync-proxy

Thin **FastAPI** service: **`POST /v1/invoke`** (KMBL contract) → **`openclaw agent --json`** on the **same machine**.

## When to use

- OpenClaw/KiloClaw exposes **`/hooks/agent`** (async) but KMBL needs **synchronous** structured JSON.
- Run this **on the VPS** next to OpenClaw where the `openclaw` CLI is installed.

## Run

```bash
export OPENCLAW_SYNC_PROXY_TOKEN="same-as-kmb-KILOCLAW_API_KEY"
export OPENCLAW_SYNC_PROXY_HOST=0.0.0.0
export OPENCLAW_SYNC_PROXY_PORT=8090
pip install -e .
python -m uvicorn openclaw_sync_proxy.main:app --host 0.0.0.0 --port 8090
```

Or: `openclaw-sync-proxy` if installed as a console script.

## Env

| Variable | Purpose |
|----------|---------|
| `OPENCLAW_SYNC_PROXY_TOKEN` | Required. Bearer token; must match orchestrator `KILOCLAW_API_KEY`. |
| `OPENCLAW_SYNC_PROXY_HOST` / `OPENCLAW_SYNC_PROXY_PORT` | Bind (defaults `0.0.0.0:8090`). |
| `OPENCLAW_EXECUTABLE` | Default `openclaw`. |
| `OPENCLAW_TIMEOUT_SEC` | Subprocess timeout (default 300). |

## KMBL orchestrator

```
KILOCLAW_TRANSPORT=http
KILOCLAW_BASE_URL=https://<your-proxy-public-url>
KILOCLAW_INVOKE_PATH=/v1/invoke
KILOCLAW_API_KEY=<same as OPENCLAW_SYNC_PROXY_TOKEN>
```

**Deployment runbook (VPS, HTTPS, curl, KMBL env):** **`DEPLOY.md`** in this folder.

Full design: **`docs/15_KILOCLAW_SYNC_ADAPTER.md`**.
