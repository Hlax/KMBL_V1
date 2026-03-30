# Running the orchestrator on a VPS

The orchestrator is a normal **FastAPI (ASGI)** app. It is **not** designed for Vercel’s Python runtime; run it on a **VM**, **container**, or **process manager** you control.

## Prerequisites

- Python **3.10+**
- Dependencies: `pip install -e ".[dev]"` from `services/orchestrator` (or lockfile in CI)
- Network: outbound HTTPS to **Supabase** and to **KiloClaw** (Tailscale or private IP is fine)

## Configuration

1. Copy env from `.env.example` at the **repository root** (or set variables in systemd / Docker).
2. Required for production persistence:

   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`

3. Required for real KiloClaw calls:

   - `KILOCLAW_TRANSPORT=http` (or `auto` if `KILOCLAW_API_KEY` is set)
   - `KILOCLAW_BASE_URL` — origin only, e.g. `http://100.x.x.x:18789` or `https://gateway.internal`
   - `KILOCLAW_INVOKE_PATH=/v1/chat/completions` (unless your gateway differs)
   - `KILOCLAW_API_KEY` — same secret the gateway expects (`gateway.auth.token` / proxy token)

4. Bind:

   - `ORCHESTRATOR_HOST=0.0.0.0` to listen on all interfaces behind nginx/Caddy
   - `ORCHESTRATOR_PORT=8000` (or any free port; align reverse proxy)

## Safe env loading

- Settings load from (in order, later overrides earlier): repo `.env`, `.env.local`, `services/orchestrator/.env`, `services/orchestrator/.env.local`.
- **`get_settings()` is cached** for the process lifetime. After changing env on disk, **restart the process** (systemd `restart`, container recreate, etc.).

## Reverse proxy

- Terminate TLS at **Caddy**, **nginx**, or a cloud load balancer.
- Forward to `http://127.0.0.1:<ORCHESTRATOR_PORT>`.
- Preserve `Host` and forward `X-Forwarded-*` if your ASGI stack needs scheme for redirects (uvicorn/FastAPI usually fine without).

## Process supervision (example: systemd)

```ini
[Service]
WorkingDirectory=/opt/kmbl/KMBL_V1/services/orchestrator
EnvironmentFile=/etc/kmbl/orchestrator.env
Environment=PYTHONPATH=src
ExecStart=/opt/kmbl/KMBL_V1/services/orchestrator/.venv/bin/uvicorn kmbl_orchestrator.api.main:app --host 0.0.0.0 --port 8000
Restart=always
```

Adjust paths and use `python -m kmbl_orchestrator.api.main` if you prefer settings-driven host/port from env (see `config.py`).

## Health check

- `GET /health` — includes effective KiloClaw transport, base URL, invoke path, **boolean** env flags (no secrets).

## Smoke tests

- **Roles (HTTP to KiloClaw):** `POST /orchestrator/invoke-role` — see root `.env.example` comments for example bodies per role.
- **Full graph (no DB):** from `services/orchestrator`:

  `set PYTHONPATH=src` then `python scripts/smoke_graph_e2e.py`

  Uses in-memory repository + your current KiloClaw/stub settings.

## Scripts in this directory

| Script | Purpose |
|--------|---------|
| `scripts/smoke_graph_e2e.py` | Planner → generator → evaluator graph smoke (in-memory repo) |
| `scripts/tunnel-cloudflared.ps1` / `.sh` | Dev: run **cloudflared** → public HTTPS to local uvicorn (see `docs/17_LOCAL_TUNNEL_DEV.md`) |
| `scripts/tunnel-ngrok.ps1` / `.sh` | Dev: run **ngrok** → public HTTPS to local uvicorn |

## Local persisted run (Supabase)

End-to-end checklist: **`docs/LOCAL_MILESTONE_RUN.md`**.
