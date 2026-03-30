# KMBL orchestrator (FastAPI + LangGraph)

Python service: **FastAPI** HTTP API and **LangGraph** run loop. Runs on a **VPS/VM** (or locally); **not** aimed at Vercel’s serverless Python runtime.

## Quick local run

From `services/orchestrator`:

```bash
# Windows PowerShell
$env:PYTHONPATH="src"
..\.venv\Scripts\python.exe -m uvicorn kmbl_orchestrator.api.main:app --host 127.0.0.1 --port 8010
```

Or use `python -m kmbl_orchestrator.api.main` so host/port come from env (see repo-root `.env.example`).

**After editing `.env` / `.env.local`, restart the process** — `get_settings()` is cached.

## Layout

| Area | Role |
|------|------|
| `kmbl_orchestrator/api/main.py` | HTTP routes (`/health`, graph runs, `invoke-role`) |
| `kmbl_orchestrator/graph/app.py` | LangGraph: planner → generator → evaluator → decision |
| `kmbl_orchestrator/contracts/` | Stable `RoleProvider` + Pydantic wire contracts for role JSON |
| `kmbl_orchestrator/providers/kiloclaw.py` | KiloClaw HTTP / CLI / stub — implements `invoke_role` |
| `kmbl_orchestrator/persistence/` | Supabase or in-memory repository |

## Smoke tests

| Command | Purpose |
|---------|---------|
| `POST /orchestrator/invoke-role` | Single role (examples in Swagger for planner / generator / evaluator) |
| `python scripts/smoke_graph_e2e.py` | Full graph with **in-memory** repo (`PYTHONPATH=src`) |
| `python scripts/local_persisted_run_smoke.py` | Health + `runs/start` + `runs/{id}` against a **running** server (needs Supabase + KiloClaw in env) |

See **`docs/LOCAL_MILESTONE_RUN.md`** for the full local Supabase milestone.

## Docs

- Repository root [`README.md`](../../README.md)
- [`DEPLOY.md`](DEPLOY.md) — VPS, systemd, reverse proxy, env
- [`../../docs/16_DEPLOYMENT_ARCHITECTURE.md`](../../docs/16_DEPLOYMENT_ARCHITECTURE.md) — end-to-end deployment model
- [`../../docs/17_LOCAL_TUNNEL_DEV.md`](../../docs/17_LOCAL_TUNNEL_DEV.md) — **cloudflared / ngrok** so Vercel can reach localhost without a VPS
