# Live validation report — Supabase RPC hardening

## Latest run: success (after SQL applied in Supabase SQL Editor)

**Environment (non-secret):**

| Field | Value |
|--------|--------|
| Entrypoint | `scripts/live_validation_from_settings.py` → `validate_supabase_rpc_live.py` |
| Project | `qcbnudujljopnkdztmkt` (from `SUPABASE_URL`) |

### Captured output (verbatim)

```
[migration file] C:\Users\guestt\OneDrive\Desktop\KMBL\KMBL_V1\supabase\migrations\20260402183000_atomic_staging_rpc.sql OK
[supabase_migrations] no row matching %20260402183000% - if you pasted SQL manually, ensure it ran on THIS database; or run: supabase db push / SQL editor against project linked to this URL.
[pg_catalog] OK - all kmbl_* RPCs present in public schema
[rpc kmbl_thread_advisory_xact_lock] OK
[rpc kmbl_atomic_upsert_working_staging] OK (insert/upsert)
[rpc invalid name] OK - surfaced error: APIError: {'message': 'Could not find the function public.kmbl___nonexistent_rpc___(p_thread_id) in the schema cache', 'code': 'PGRST202', 'hint': 'Perhaps you meant to call the function public.kmbl_a ...
[concurrency] wall_two_parallel_rpc_s=0.287 single_rpc_s=0.113
[concurrency] OK - wall time consistent with serialized critical section (heuristic)
---
NEXT: run a real graph through staging_node and operator approve; confirm timeline shows persistence=supabase_rpc / mutation_path in graph_run_event payloads (see docs/LIVE_VALIDATION_REPORT.md).
```

### Re-run (agent, same repo / `.env.local`, exit 0)

Command: `py -3 scripts\live_validation_from_settings.py` from repo root (this environment has no `python` on `PATH`; the Windows `py` launcher is used). Output matched the checks above; concurrency timings differ slightly run to run:

```
[concurrency] wall_two_parallel_rpc_s=0.277 single_rpc_s=0.118
[concurrency] OK - wall time consistent with serialized critical section (heuristic)
```

### Interpretation (proven vs inferred)

| Check | Result | Class |
|--------|--------|--------|
| `pg_proc` / `public.kmbl_*` (all four expected RPCs) | **Proven OK** | `[pg_catalog] OK - all kmbl_* RPCs present in public schema` |
| `kmbl_thread_advisory_xact_lock` via PostgREST + service role | **Proven OK** | |
| `kmbl_atomic_upsert_working_staging` via PostgREST + service role | **Proven OK** | |
| Invalid RPC name | **Proven OK** | Explicit **PGRST202** + message; PostgREST may suggest a similar function (`hint`) — **not** a silent success |
| Same-`thread_id` concurrent upserts | **Proven (heuristic)** | Example runs: parallel wall ~2.4× single (~0.28s vs ~0.12s) — script reports serialization-consistent timing; **not** a formal proof under load |
| Row in `supabase_migrations.schema_migrations` | **Proven: still empty** | **Inferred:** normal when SQL is run **manually** in the Dashboard; the CLI migration table is only populated by `supabase db push` / tracked migrations. **Not** evidence that objects are missing — `pg_catalog` is the source of truth here. |
| Orchestrator graph / staging_node / approve / timeline `persistence` / `mutation_path` | **Not tested** | Requires a real graph run + operator actions against this project (next step in script footer). |

**Conclusion:** RPC hardening is **live** for **PostgREST + direct Postgres** checks above. Remaining gap is **product-level** validation (orchestrator runtime + event payloads), not RPC existence.

---

## Previous run: 2026-04-03 (before migration objects existed)

Direct Postgres showed **`public.kmbl_*` count: 0**; PostgREST returned **PGRST202** for all RPCs. Root cause: migration SQL had not been applied to the connected database (see earlier troubleshooting: **do not paste SQL into PowerShell** — use **Supabase SQL Editor** or `psql -f`).

---

## Tooling reference

- **`scripts/validate_supabase_rpc_live.py`** — RPC smoke, invalid RPC, concurrency heuristic, optional `psycopg` + `supabase_migrations` probe.
- **`scripts/live_validation_from_settings.py`** — loads orchestrator `Settings()` (`.env.local`).
- **`scripts/diag_supabase_kmbl_targets.py`** — lists `public.kmbl_*` and compares project ref in URLs.

---

## Summary (four sections) — current state

| Section | Content |
|---------|---------|
| **Proven working** | All four `kmbl_*` functions in `public`; service-role PostgREST can call `kmbl_thread_advisory_xact_lock` and `kmbl_atomic_upsert_working_staging`; invalid RPC returns explicit **PGRST202**; concurrent upsert wall time > single-RPC baseline (heuristic). |
| **Proven failing** | *(None in latest run.)* |
| **Fixed in this pass** | *(N/A — this document update only.)* |
| **Still future work** | End-to-end orchestrator run (staging_node, approve, rollback) and confirmation that `graph_run_event` payloads include `persistence` / `mutation_path` in practice; optional: use `supabase db push` if you want `schema_migrations` rows for audit. |
