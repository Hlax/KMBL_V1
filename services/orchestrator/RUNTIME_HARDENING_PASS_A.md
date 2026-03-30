# Pass A: Runtime Hardening (summary)

## Files changed (or added)

| Area | Path |
|------|------|
| Config | `src/kmbl_orchestrator/config.py` |
| Domain | `src/kmbl_orchestrator/domain.py` (`post_step` checkpoint kind, `GraphRunEventRecord`) |
| API | `src/kmbl_orchestrator/api/main.py` |
| Graph | `src/kmbl_orchestrator/graph/app.py` |
| Roles | `src/kmbl_orchestrator/roles/invoke.py` |
| KiloClaw | `src/kmbl_orchestrator/providers/kiloclaw.py` |
| Persistence | `src/kmbl_orchestrator/persistence/repository.py`, `persistence/supabase_repository.py` |
| Contracts | `src/kmbl_orchestrator/contracts/normalized_errors.py` (new), `role_inputs.py` (new), `persistence_validate.py` (new) |
| Runtime | `src/kmbl_orchestrator/runtime/__init__.py`, `run_events.py`, `stale_run.py`, `run_failure_view.py` (new) |
| Migration | `supabase/migrations/20260329120000_graph_run_event.sql` |
| Env example | repo root `.env.example` |
| Tests | `tests/test_runtime_hardening.py` (new), `tests/test_kiloclaw_http_chat_completions.py` |

## What was implemented

1. **Stale-run reconciliation** — `ORCHESTRATOR_RUNNING_STALE_AFTER_SECONDS` (default 3600; `0` disables). On **GET** `/orchestrator/runs/{id}`, if the row is still `running` and older than the threshold, it is marked **failed**, an **interrupt** checkpoint is written with `error_kind: orchestrator_stale_run` and the standard stale message, and a **timeline** event is recorded. Helper `reconcile_all_stale_running_graph_runs` exists for batch/test use.

2. **GET run status** — After optional stale reconcile, failure fields are resolved via `build_run_failure_view`: failed **role_invocation** (with `error_kind` on the payload), else **interrupt** `orchestrator_error` (maps legacy `persist_or_graph` to **`graph_error`** for display), else a safe fallback message. Response includes **`timeline_events`** (append-only window).

3. **KiloClaw boundary validation** — **Outbound**: Pydantic **role input** models (`PlannerRoleInput`, `GeneratorRoleInput`, `EvaluatorRoleInput`) validate requests in `DefaultRoleInvoker` before calling the provider; failures persist a **failed** `role_invocation` with `error_kind: contract_validation`. **Inbound**: existing wire contracts remain; **second-pass** `validate_role_output_for_persistence` runs after a successful provider return and before persisting `build_spec` / downstream rows; failures mark invocation failed and raise `RoleInvocationFailed` with `contract_validation`. Provider envelopes include **`error_kind`** (e.g. `provider_error`, `contract_validation`).

4. **Failure taxonomy** — Normalized kinds used in payloads and GET: `role_invocation`, `contract_validation`, `provider_error`, `persistence_error`, `graph_error`, `orchestrator_stale_run`, `sandbox_error`, plus legacy `persist_or_graph` mapped to **`graph_error`** when read from old interrupt rows. `POST /orchestrator/runs/start` persistence errors now use **`persistence_error`** in the HTTP 500 `detail`. Background wrapper interrupt uses **`graph_error`** (replaces `persist_or_graph`).

5. **Run timeline** — Table **`graph_run_event`**; `append_graph_run_event` records `graph_run_started`, `checkpoint_written`, role start/complete, `decision_made`, `graph_run_completed`, `graph_run_failed`, etc.

6. **Checkpoints** — **pre_role** before each role (tagged gate), **post_step** after each successful role, **interrupt** before terminal failure (`RoleInvocationFailed` and generic `Exception` in `run_graph`), **post_role** still holds final graph state for snapshots. **thread.current_checkpoint_id** updated only on final **post_role** (unchanged semantics).

7. **Tests** — `tests/test_runtime_hardening.py` covers fast start, terminal completed poll, persistence contract failure, provider failure surfacing, stale reconcile, background graph error, idempotent GET after stale, and role input validation.

## New env vars

- **`ORCHESTRATOR_RUNNING_STALE_AFTER_SECONDS`** — Integer seconds; default **3600** in `Settings`. **`0`** disables stale reconciliation.

## Local test commands

```powershell
cd C:\path\to\KMBL_V1\services\orchestrator
pip install -e ".[dev]"
$env:PYTHONPATH = "src"
$env:SUPABASE_URL = ""
$env:SUPABASE_SERVICE_ROLE_KEY = ""
$env:KILOCLAW_TRANSPORT = "stub"
python -m pytest tests -q
python scripts/smoke_graph_e2e.py
```

Apply Supabase migration before using the timeline against a real project DB:

```powershell
# from repo root, using your usual Supabase CLI workflow
supabase db push
```

## Manual verification checklist

- [ ] Apply **`20260329120000_graph_run_event.sql`** to Supabase; without it, event inserts fail in production mode.
- [ ] `POST /orchestrator/runs/start` returns **`status: running`** quickly.
- [ ] `GET /orchestrator/runs/{id}` shows **`running` → `completed`** with **`timeline_events`** including **`graph_run_completed`**.
- [ ] Force a stale run (old `started_at`, still `running`); GET returns **`failed`**, **`error_kind: orchestrator_stale_run`**.
- [ ] `GET /health` includes **`orchestrator_running_stale_after_seconds`**.
- [ ] Invalid role **input** to `invoke` (or graph) yields **`contract_validation`** on failed invocation / GET.

## Known limitations (after this pass)

- Still **same-process** `BackgroundTasks` / thread pool; no durable queue or retry.
- **Supabase client + singleton repository** concurrency guarantees unchanged.
- **Stale threshold** is time-based only; a legitimately slow run longer than the threshold can be marked failed (tune **`ORCHESTRATOR_RUNNING_STALE_AFTER_SECONDS`** for your environment).
- **Strict persistence** rules for planner `build_spec` require non-empty **`type`** and **`title`**; providers that omit `type` will fail at persistence validation until contracts or payloads are adjusted.
- **Planner/generator/evaluator role JSON contracts** for wire shape are unchanged except for added **input** validation and **persistence** pass; deeper semantic validation is out of scope.
