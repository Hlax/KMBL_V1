# KMBL_V1

KMBL is the orchestrator and control plane. External role execution (Planner, Generator, Evaluator) is hosted in KiloClaw; this repository implements the execution spine (Python + LangGraph + FastAPI), shared contracts, a Supabase-oriented storage stub, and a minimal Next.js control-plane shell.

Canon architecture and naming live under [`docs/`](docs/).

## Repository layout

| Path | Purpose |
|------|---------|
| [`docs/`](docs/) | Canon specifications (source of truth) |
| [`services/orchestrator/`](services/orchestrator/) | FastAPI service, LangGraph runtime, role invocation, normalization, placeholder persistence |
| [`packages/contracts/`](packages/contracts/) | Shared placeholder schemas (Zod) for API and persistence shapes |
| [`packages/config/`](packages/config/) | Typed environment parsing for JS/TS consumers |
| [`packages/storage/`](packages/storage/) | TypeScript Supabase client package for future app-side use (orchestrator uses `supabase-py` directly) |
| [`apps/control-plane/`](apps/control-plane/) | Minimal Next.js UI (home + status placeholder) |

## Prerequisites

- Python 3.10+
- Node.js 20+ (for workspaces and the control-plane app)

## Orchestrator (Python)

Set **`ORCHESTRATOR_HOST`**, **`ORCHESTRATOR_PORT`**, and optionally **`ORCHESTRATOR_RELOAD`** in [`.env.example`](.env.example) → repo root **`.env`** or **`.env.local`** (and optionally under `services/orchestrator/`). The orchestrator resolves these files from the repo layout (not your shell cwd), in order: repo `.env`, repo `.env.local`, `services/orchestrator/.env`, `services/orchestrator/.env.local` — later overrides earlier.

From the repository root:

```bash
cd services/orchestrator
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

**Recommended (no hardcoded host/port):** run via the embedded entrypoint so host, port, and reload come from env:

```bash
cd services/orchestrator
.\.venv\Scripts\python.exe -m kmbl_orchestrator.api.main
```

**Alternative — uvicorn CLI (PowerShell):** set `ORCHESTRATOR_HOST` and `ORCHESTRATOR_PORT` in the session (or paste from repo root `.env.local`), then:

```powershell
cd services\orchestrator
.\.venv\Scripts\python.exe -m uvicorn kmbl_orchestrator.api.main:app --reload --host $env:ORCHESTRATOR_HOST --port $env:ORCHESTRATOR_PORT
```

If those `$env:` variables are not set, use the **recommended** command above instead; it loads `.env` / `.env.local` automatically. Omit `--reload` when `ORCHESTRATOR_RELOAD=false` in env if you use `python -m kmbl_orchestrator.api.main`.

On **Windows**, binding sometimes fails with **WinError 10013** — use `127.0.0.1` and a free port in `.env.local`, not hardcoded in the command. If `--reload` misbehaves (OneDrive paths), set `ORCHESTRATOR_RELOAD=false` or run uvicorn without `--reload`.

To see whether a port is already taken: `netstat -ano | findstr :<port>`.

Repos under **OneDrive** can add file-lock noise during installs or reload; if problems repeat, cloning to a non-synced path (for example `C:\dev\KMBL_V1`) often helps.

**Endpoints** (use the same host/port as in your env):

- Health: `GET http://<ORCHESTRATOR_HOST>:<ORCHESTRATOR_PORT>/health`
- Internal run start (per [`docs/12_API_AND_SERVICE_LAYER.md`](docs/12_API_AND_SERVICE_LAYER.md)): `POST /orchestrator/runs/start`
- Run status: `GET /orchestrator/runs/{graph_run_id}`

Keep **`NEXT_PUBLIC_ORCHESTRATOR_URL`** in [`apps/control-plane/.env.local`](apps/control-plane/.env.example) aligned with that host/port (e.g. `http://127.0.0.1:8010`).

**Optional API key (production):** set `ORCHESTRATOR_API_KEY` so mutating routes require `X-API-Key` or `Authorization: Bearer` (same value). When unset, auth is disabled (local dev). See [docs/16_DEPLOYMENT_ARCHITECTURE.md](docs/16_DEPLOYMENT_ARCHITECTURE.md).

**Graph run execution model:** in-process `BackgroundTasks` by default; for durable queue/worker patterns see [docs/18_DURABLE_GRAPH_RUNS.md](docs/18_DURABLE_GRAPH_RUNS.md). Evaluator iterate-vs-stage policy (alignment vs status) is documented in [docs/19_EVALUATOR_DECISION_POLICY.md](docs/19_EVALUATOR_DECISION_POLICY.md).

**Supabase credentials:** pull from the Supabase dashboard (Project Settings → API / Database) into repo root `.env` or `.env.local`; the Cursor Supabase extension can help discover values, but the source of truth remains your project. Do not commit secrets.

**Persistence:** If both `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are set (non-empty), the API uses **`SupabaseRepository`** (Phase 1 tables via supabase-py). If either is missing, it falls back to **`InMemoryRepository`** (same process only). Restart the orchestrator after changing env.

**Graph run invariant:** `persist_graph_run_start()` must run before `run_graph()` (the `POST /orchestrator/runs/start` handler does this). Calling `run_graph` with a `graph_run_id` that is not in the repository raises a clear error.

**Thread pointer:** After each completed run, `thread.current_checkpoint_id` is set to the post-run checkpoint (resume / thread loading). Env changes still require a process restart; tests can call `reset_repository_singleton_for_tests()`.

**Raw JSON columns:** `raw_payload_json` on build_spec / build_candidate / evaluation_report stays null until real KiloClaw payloads are stored — normalized JSON columns remain the source of truth for product logic.

**Checkpoint payloads:** Full `state_json` per checkpoint is intentional for v1; compaction or splitting is deferred.

## Control plane (Next.js)

```bash
npm install
npm run control-plane
```

Open `http://localhost:3000` (home) and `http://localhost:3000/status` (orchestrator health check).

### Environment files

| File | Purpose |
|------|---------|
| [`.env.example`](.env.example) (repo root) | Template for orchestrator + shared Supabase + default `NEXT_PUBLIC_*` |
| **Repo root `.env`** | Copy from `.env.example`; safe place for `SUPABASE_SERVICE_ROLE_KEY` and orchestrator vars (orchestrator resolves `../../.env` when run from `services/orchestrator`) |
| [`apps/control-plane/.env.example`](apps/control-plane/.env.example) | Template for the Next app only |
| **`apps/control-plane/.env.local`** | Your local `NEXT_PUBLIC_ORCHESTRATOR_URL` (and optional future `NEXT_PUBLIC_SUPABASE_*`) — **do not commit** |

**What to put in `apps/control-plane/.env.local` for local dev:** at minimum `NEXT_PUBLIC_ORCHESTRATOR_URL` pointing at your running FastAPI URL (for example `http://127.0.0.1:8010`). You do **not** need Supabase keys in the control-plane until the UI calls Supabase from the browser; v1 persistence is expected to go through the orchestrator with `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` in the root `.env`.

### Supabase rollout order (recommended)

1. **Supabase project + env** — set `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and optionally `SUPABASE_DB_URL` in repo root `.env`.
2. **Migrations / schema** — align tables with [`docs/07_DATA_MODEL_AND_STACK_MAP.md`](docs/07_DATA_MODEL_AND_STACK_MAP.md) Phase 1 (start with `thread`, `checkpoint`, `graph_run`, `role_invocation`, `build_spec`, `build_candidate`, `evaluation_report`).
3. **DB-backed repository** — replace `InMemoryRepository` in the orchestrator (supabase-py for speed in v1 is fine; Postgres-style access can come later).
4. **One real persisted run** — `POST /orchestrator/runs/start` through planner → generator → evaluator with rows stored.
5. **Real KiloClaw client** — replace the stub only after persistence is trustworthy.
6. **Role-config testing**, then **identity bootstrap** and the rest of the identity layer.

## Known limitations (scaffold)

- The pinned Next.js release may show `npm audit` advisories; upgrade to a patched minor when your team is ready, then re-run `npm run build` for the control-plane.
- Python dependencies are pinned in `services/orchestrator/pyproject.toml` for reproducible installs; bump LangGraph deliberately when you adopt newer graph APIs.

## What is intentionally thin

- KiloClaw calls are stubbed; real HTTP/MCP wiring is TODO in `services/orchestrator`.
- The orchestrator can persist to Supabase when env is set; `packages/storage` remains a TS stub for future app-side use.
- No auth, no elaborate UI, no deployment manifests beyond run commands above.

## Next implementation steps

Follow the **Supabase rollout order** above (schema → DB repository → persisted run → real KiloClaw → identity). Additional items:

1. Harden validation of role payloads against [`docs/07_DATA_MODEL_AND_STACK_MAP.md`](docs/07_DATA_MODEL_AND_STACK_MAP.md) §4 and [`docs/09_KILOCLAW_ROLE_CONFIGS.md`](docs/09_KILOCLAW_ROLE_CONFIGS.md).
2. Add async or background execution for long graph runs if needed; optional webhook from [`docs/12_API_AND_SERVICE_LAYER.md`](docs/12_API_AND_SERVICE_LAYER.md) §10.
3. Flesh out the control-plane to call orchestrator APIs from server actions or route handlers (still no direct KiloClaw access from the browser).
