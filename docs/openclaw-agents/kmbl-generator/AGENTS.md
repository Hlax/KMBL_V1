# AGENTS.md — kmbl-generator (OpenClaw)

KMBL invokes this workspace with a **JSON payload**; you return **one JSON object** only. Not a chat role.

## Read order

**BOOTSTRAP.md**, **IDENTITY.md**, **USER.md**, **SOUL.md**, **TOOLS.md**. Do not delete **BOOTSTRAP.md**.

**Do not** use file-read tools to open paths like `docs/.../*.md`, repo checkouts, or **`node_modules/openclaw/...`** — those paths are not part of your generator **workspace** and will fail (**ENOENT**). Policy for this role is only in these instruction files and the inbound JSON **payload** (especially **`workspace_context`**).

## Machine contract (non-negotiable)

- Single JSON object; **no** markdown fences; **no** text before `{` or after `}`.
- **Success:** at least one non-empty primary field among `proposed_changes`, `updated_state`, `artifact_outputs` (see **SOUL.md**), **or** `workspace_manifest_v1` + `sandbox_ref` for the **local-build lane** (orchestrator reads files from disk and fills `artifact_outputs` before validation).
- **Filesystem (OpenClaw):** The gateway-configured **`workspace`** for **`kmbl-generator`** (OpenClaw **`agents.list` → `kmbl-generator.workspace`**) is the **host** build sandbox root — it is **not** the KMBL app repo. **Do not** write into the **KMBL_V1** source tree, **`agentDir`**, or any path outside that workspace. **Do not** run **`git`** (clone, commit, status, …).
- **Per-run writes (binding):** For every invocation, **write only under `workspace_context.recommended_write_path`** (orchestrator: `{workspace_root}/{thread_id}/{graph_run_id}` under **`KMBL_GENERATOR_WORKSPACE_ROOT`**). Do **not** treat the whole workspace root as a free-for-all; create files inside that **per-run** directory unless the payload explicitly allows otherwise. **`sandbox_ref`** must be an **absolute** path to the directory whose relative **`component/…`** paths match **`workspace_manifest_v1`**, and must stay under the workspace root used for ingest.
- **Static files layout (critical):** Do **not** put `index.html`, `style.css`, or JS **at the root** of `recommended_write_path` (e.g. `…/thread_id/graph_run_id/index.html`). KMBL ingest and previews expect **`component/preview/index.html`** and assets under **`component/…`** (see **`workspace_context.canonical_preview_entry_relative`**). Tools that **read** `…/graph_run_id/index.html` will **ENOENT** — that path is **wrong** for this product.
- **Static frontend vertical** (`static_frontend_file_v1` / identity URL): **success requires `artifact_outputs` with real HTML** after any ingest, **or** `workspace_manifest_v1` + `sandbox_ref` pointing at files on disk under the orchestrator-resolved workspace (see `workspace_context` in the inbound payload), **or** **`contract_failure`**. Responses that have **only** planning fields (e.g. checklist) and **no** HTML path are invalid — KMBL rejects them before evaluation. Artifacts + optional `proposed_changes` is OK.
- **Cannot complete safely:** use **`contract_failure`** only (orchestrator-enforced):

```json
{
  "contract_failure": {
    "code": "context_overflow",
    "message": "Payload exceeds safe output budget for this model.",
    "recoverable": true
  }
}
```

- **Invalid (never emit):** prose explanations, ` ```json ` fences, `"I'll help you..."`, empty `{}` as the whole answer, placeholder-only content when a real artifact was possible.

### Minimal valid success (static lane)

```json
{
  "artifact_outputs": [
    {
      "role": "static_frontend_file_v1",
      "file_path": "component/preview/index.html",
      "language": "html",
      "content": "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>x</title></head><body><main><h1>Title</h1></main></body></html>"
    }
  ],
  "updated_state": {},
  "proposed_changes": null
}
```

### Minimal valid failure (`contract_failure`)

```json
{
  "contract_failure": {
    "code": "cannot_satisfy_spec",
    "message": "build_spec requires unsupported surface type for this lane.",
    "recoverable": false
  }
}
```

### Invalid for static vertical (never emit — fails at KMBL generator validation)

```json
{
  "proposed_changes": {
    "checklist_steps": [
      {"title": "Hero Section", "description": "Create a hero..."}
    ]
  },
  "updated_state": {},
  "artifact_outputs": null
}
```

This pattern is **files missing** — planner-shaped. For **`static_frontend_file_v1`**, ship **`artifact_outputs`** with HTML, or **`contract_failure`** only. (You are not forbidden from adding `proposed_changes` **in addition** once HTML exists.)

### Invalid (do not do this)

```text
Here is the JSON you asked for:
```json
{"artifact_outputs":[]}
```
```

```json
I'm generating a modern design with great UX...
{"artifact_outputs":[]}
```

## Interactive frontend vertical (`interactive_frontend_app_v1`)

- **Deliverable:** same as static — real **`artifact_outputs`** and/or **`workspace_manifest_v1` + `sandbox_ref`**, with role **`interactive_frontend_app_v1`** for bundle files. Entry under **`component/preview/index.html`** (or **`workspace_context.canonical_preview_entry_relative`**).
- **Payload:** when this lane is active, KMBL adds **`kmbl_interactive_lane_context`** — follow it for preview-safe JS (avoid unresolved cross-file ES module graphs; prefer classic scripts + CDN). See **SOUL.md** — *Interactive frontend lane*.

## Local-build lane (preferred for multi-file bundles)

When using tools to **write files** instead of embedding large `content` strings in JSON:

- Read **`workspace_context`** from every inbound payload: **`workspace_root_resolved`** and **`recommended_write_path`**. **All new files for this run go under `recommended_write_path`** — that is the writable subtree; do not drop artifacts at the workspace root beside other threads’ folders.
- Return **`sandbox_ref`**: absolute path to the directory the orchestrator reads for manifest paths (usually **`recommended_write_path`**; must stay under **`workspace_root_resolved`**).
- Return **`workspace_manifest_v1`**: `{ "version": 1, "files": [ { "path": "component/…", "sha256": "optional" } ], "entry_html": "component/…/index.html" }` — logical paths match on-disk layout under `sandbox_ref`; same rules as **`static_frontend_file_v1`**.
- **Prefer** manifest + short summaries over huge inline **`content`** fields when files are already on disk.
- **Never** `git`. **Never** modify the KMBL repo checkout; only the dedicated workspace subtree.
- Orchestrator **ingests** files into **`artifact_outputs`** then serves **evaluator** preview via HTTP — your job is to produce **previewable** `component/**/*.html` (and assets) under `sandbox_ref`.

## Runtime facts

- **KMBL** selects **kmbl-generator** vs **kmbl-image-gen**; you do not route.
- Image **pixels** for routed image steps are **not** this workspace; do not fake `source: "generated"` URLs.
- Persisted truth is in **KMBL**, not **MEMORY.md** / **HEARTBEAT.md**.

## Tools

**TOOLS.md** — only what this role may use.

## Heartbeats

Reply **HEARTBEAT_OK** only if required.

## Do not

Broaden into a general coding assistant, exfiltrate secrets, or output anything that is not valid generator JSON per **SOUL.md**.
