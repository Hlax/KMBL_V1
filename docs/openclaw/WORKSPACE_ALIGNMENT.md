# KMBL generator: OpenClaw workspace vs orchestrator root

**Audience:** KMBL repo operators and developers reading this git tree. **Do not** cite this path in **OpenClaw agent instructions** (`docs/openclaw-agents/kmbl-generator/`) — models may try to **tool-read** it and resolve a bogus path under `node_modules/openclaw`. Generator policy lives in **AGENTS.md** / **USER.md** / **TOOLS.md** only.

**OpenClaw JSON:** **`agentDir`** must point at the **instruction** folder (markdown), e.g. your clone of **`docs/openclaw-agents/kmbl-generator`**. **`workspace`** must point at the **build sandbox** (e.g. **`…/.openclaw/workspace-kmbl-generator`**). **Do not** set **`agentDir`** to the **`workspace`** path — instructions and generated files are different trees.

Machine-agnostic reference. **Do not commit** real home-directory paths into shared config; set them only on the host that runs OpenClaw + the orchestrator.

## Same absolute path (required for local-build + ingest)

| Setting | Role |
|--------|------|
| OpenClaw **`agents.list[]`** → **`kmbl-generator.workspace`** | Filesystem root where the generator agent may create files. Typical layout: **`<home>/.openclaw/workspace-kmbl-generator`** (expand `~` / `%USERPROFILE%` to an absolute path in JSON on Windows). |
| Orchestrator **`KMBL_GENERATOR_WORKSPACE_ROOT`** | Same absolute path as **`kmbl-generator.workspace`**. Ingest checks **`sandbox_ref`** under this root. |

If these differ, **`workspace_context.recommended_write_path`** may not match disk the orchestrator can read, and ingest fails.

## Common misconfiguration

- **`kmbl-generator`** must use its **own** folder: **`…/workspace-kmbl-generator`**, not **`…/workspace-kmbl-planner`** (or evaluator). Copy-pasting the planner block into the generator entry leaves **`workspace`** pointing at the wrong tree; builds may still land under the correct path if tools use **`workspace_context.recommended_write_path`**, but OpenClaw’s configured sandbox and orchestrator **`KMBL_GENERATOR_WORKSPACE_ROOT`** will disagree — fix the JSON so **`workspace`** matches where you want generator files (e.g. **`C:\Users\<you>\.openclaw\workspace-kmbl-generator`** on Windows).

## `agentDir` vs `workspace` (OpenClaw)

| Field | Purpose |
|-------|---------|
| **`agentDir`** | Instructions only: markdown (**AGENTS.md**, **SOUL.md**, …) copied or symlinked from **`docs/openclaw-agents/kmbl-generator/`**. **Not** the build output area. |
| **`workspace`** | **Build sandbox** for generated files. This is what must align with **`KMBL_GENERATOR_WORKSPACE_ROOT`**. |

## Per-run writes (generator behavior)

The orchestrator sends **`workspace_context.recommended_write_path`** = `{root}/{thread_id}/{graph_run_id}` under **`workspace_root_resolved`**.

- The generator must **write only under `recommended_write_path`** for that run (not arbitrary paths under the broader workspace root, and never the KMBL app repo).
- **`sandbox_ref`** in the JSON response should point at the directory tree that contains **`component/`** for ingest (usually equals **`recommended_write_path`** or a parent that still lies under the workspace root).

## Repo-tracked JSON

**`docs/openclaw/openclaw.json`** uses placeholders (`C:\Users\<you>\...`). Copy to your gateway host (e.g. **`~/.openclaw/openclaw.json`**) and replace with your real paths.

## Troubleshooting: `[tools] read failed: ENOENT` under `…\workspace-kmbl-generator\{thread_id}\{graph_run_id}\component\…`

OpenClaw logged a **read** to a path that does **not** exist on disk. Common causes:

1. **Inline-only output** — The generator returned HTML in **`artifact_outputs`** (JSON) but never **wrote** `component/preview/index.html` under **`workspace_context.recommended_write_path`**. A follow-up tool or model step still tried to **read** that file.
2. **Read before write** — A **read** ran before the **write** completed in the same turn.
3. **Different on-disk layout** — Files were written under other names/paths than the path used in the **read** call.

**Mitigation (generator behavior):** Only invoke **read** on paths you have already **created** under **`recommended_write_path`** this run. If the site is delivered **only** via **`artifact_outputs`**, do not assume on-disk **`component/preview/index.html`** exists. For **manifest + disk** flows, **write** files first, then **read** if needed.

This error is from the **OpenClaw tool layer**; KMBL ingest does not perform that read. A run can still **complete** if the final JSON response was valid while a non-fatal tool read failed.

**Orchestrator ingest observability:** When manifest ingest runs, **`workspace_ingest_started`** includes a **preflight** payload (resolved roots, `recommended_write_path` vs `sandbox_ref` alignment, normalized manifest paths). **`workspace_ingest_failed`** includes **`ingest_details`** when a manifest file is missing (e.g. `ingest_failure_class`: `parent_directory_missing`, `artifact_not_found`, `possible_case_mismatch`).
