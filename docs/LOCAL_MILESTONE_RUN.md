# Local milestone: persisted graph run + control-plane status

**Goal:** One full run (planner → generator → evaluator) with rows in **Supabase**, inspected via **GET /orchestrator/runs/{id}** and the **control-plane** `/status` page.

**Not required:** Vercel, tunnels, or a VPS — everything on `127.0.0.1`.

## 1. Prerequisites

- Phase 1 migration applied to your Supabase project (`supabase/migrations/...kmbl_phase1_core_tables.sql`).
- Repo-root **`.env.local`** (or `.env`) with:
  - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
  - `KILOCLAW_*` for real HTTP transport
  - `ORCHESTRATOR_HOST`, `ORCHESTRATOR_PORT` (e.g. `127.0.0.1`, `8010`)

## 2. Start the orchestrator

```powershell
cd services\orchestrator
$env:PYTHONPATH="src"
..\.venv\Scripts\python.exe -m uvicorn kmbl_orchestrator.api.main:app --host 127.0.0.1 --port 8010
```

## 3. Verify health

```powershell
curl.exe -sS http://127.0.0.1:8010/health
```

Check **`readiness.ready_for_full_local_run`**: `true` when Supabase + KiloClaw are configured. **`repository_backend`** should be **`supabase`**.

## 4. Automated smoke (optional)

With the server running:

```powershell
cd services\orchestrator
$env:PYTHONPATH="src"
$env:ORCHESTRATOR_BASE="http://127.0.0.1:8010"
..\.venv\Scripts\python.exe scripts\local_persisted_run_smoke.py
```

## 5. Control plane (Next.js)

```powershell
cd apps\control-plane
# apps/control-plane/.env.local
# NEXT_PUBLIC_ORCHESTRATOR_URL=http://127.0.0.1:8010
npm run dev
```

Open **`/status`**: health panel + **Start run** + **Fetch run status** (uses API routes that proxy to FastAPI).

## 6. Confirm in Supabase

Table Editor: **`graph_run`**, **`role_invocation`**, **`build_spec`**, **`build_candidate`**, **`evaluation_report`**, **`checkpoint`** for the new `graph_run_id`.

## 7. Restart rule

After changing `.env`, **restart uvicorn** — `get_settings()` is **cached** for the process, so `/health` can lie until restart.

## Troubleshooting (read the response body)

| Symptom | Likely layer |
|--------|----------------|
| `POST .../runs/start` returns **200** with `"status":"failed"` and **`failure`** / **`failure_phase`** | **KiloClaw** transport/auth or **contract** (`failure.error_type`: `transport_error`, `invalid_response`, …) |
| Same response with **`error_kind":"persist_or_graph"`** and **`error_message`** | **Supabase** insert/select or graph checkpoint (see orchestrator logs for `SupabaseRepository.*`) |
| **500** with `"step":"persist_graph_run_start"` | Could not create **thread** / **graph_run** row |
| `/health` says `ready_for_full_local_run` but run still fails | Readiness is **config-only** (no live probes). Bad key or network still fails at runtime |

Orchestrator logs: search for `SupabaseRepository.` (persistence) vs KiloClaw messages (provider).
