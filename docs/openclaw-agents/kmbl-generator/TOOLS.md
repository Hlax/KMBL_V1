# TOOLS.md — kmbl-generator

## Role

KMBL orchestrates; KiloClaw runs this workspace. The generator **implements within scope**: it maps **build_spec** (+ **current_working_state**, **iteration_feedback**) to **`artifact_outputs` (primary for static sites)** and **`updated_state`**, with **`proposed_changes`** as optional traceability. For static vertical, **`proposed_changes` must not replace** real files — it can supplement them. It does not replan, pass/fail the run, publish, or invoke other roles.

## Tooling stance

- **Filesystem (two layers):** (1) OpenClaw **`workspace`** = host root for this agent (gateway **`kmbl-generator.workspace`**). (2) **Per graph run**, **read/write only under `workspace_context.recommended_write_path`** from the KMBL payload — a subdirectory under that root. Do **not** write sibling folders at the workspace root for “scratch” output; keep each run isolated under its **`recommended_write_path`**. **Do not** write to the KMBL **application repository** source tree, **`agentDir`**, or paths outside the configured **`workspace`**.
- **Read tools:** Do **not** call **read** unless the file exists at the path you **actually wrote**.
  - **Wrong (will ENOENT on KMBL layouts):** `…/workspace-kmbl-generator/<thread_id>/<graph_run_id>/index.html` or `…/style.css` at the **run folder root**.
  - **Right:** `…/<graph_run_id>/component/preview/index.html` (and CSS/JS beside it under **`component/preview/`** or **`component/…`**), matching **`artifact_outputs.path`** / **`workspace_manifest_v1.files[].path`**.
  - If you shipped HTML **only** inline in **`artifact_outputs`**, on-disk paths may not exist — do not read them. Write under **`component/`** first, then read if needed.
- **Git:** **Forbidden** — do not run `git`, `gh`, or similar. The KMBL repo is **read-only** from this role; builds are **not** committed here.
- **In scope:** Build and test commands (**npm**/**pnpm**/**vite**/etc.) **only** when run inside the allowed workspace path, plus file tools needed to emit **`artifact_outputs`** or on-disk files for **manifest ingest**. Shell is for **scoped** build steps—not open-ended exploration.
- **Out of scope (images):** Do **not** invoke server-side image provider APIs from this workspace. **KMBL** owns image generation credentials, routing, and gating. Emit **gallery_strip_image_v1** (and **ui_gallery_strip_v1** in state) **only** when schema-valid per **SOUL.md** — real **`items`**, no partial strips. When the run is routed to **`kmbl-image-gen`**, image/API failures belong in **`updated_state.kmbl_image_generation`** on that agent — **do not** represent provider failure with a fake or diagnostic **`ui_gallery_strip_v1`** object.
- **Out of scope:** Calling other agents, changing **build_spec** scope, emitting evaluator-style **status** verdicts, or orchestration fields (e.g. “next step”, “approve”) unless KMBL’s contract explicitly adds them.
- **Iteration:** **iteration_feedback** is prior evaluator output as supplied by KMBL—apply it; do not invent feedback.

## Environment (informational)

Typical hosted environments may include Debian, volume mounts, and supervisor-managed OpenClaw. Config under `/root/.kilo` is host-owned—do not modify unless the contract and deployment explicitly require it.

If a **Kilo CLI** (`kilo`) exists, use it only for **scoped** edits aligned with **build_spec**, not for unconstrained “autonomous” task runs that ignore the payload.

## Output

The only authoritative response for KMBL is the **single JSON object** in **SOUL.md** / **USER.md**. Do not rely on chat prose or markdown fences; artifacts belong inside **artifact_outputs** / **proposed_changes** / **updated_state** as structured data.

For **static HTML/CSS/JS**, either (a) emit each file as a **`static_frontend_file_v1`** object in **artifact_outputs**, or (b) write the same paths under **`workspace_context.recommended_write_path`**, then return **`sandbox_ref`** + **`workspace_manifest_v1`** so the orchestrator **ingests** into **`artifact_outputs`** (preferred when payloads would be large). Paths under **`component/`**, `language`, `content` (inline) or manifest paths on disk; optional **`bundle_id`** / **`entry_for_preview`**. KMBL normalizes and persists for **staging** / **evaluator** preview—keep files valid and cross-linked with relative paths inside **`component/`**. Do not fabricate **preview_url** unless the deployment provides one. The orchestrator assembles HTML for **candidate-preview** and working-staging routes from persisted artifacts after ingest.

For **`interactive_frontend_app_v1`**, use the same layout and tooling; read **`kmbl_interactive_lane_context`** for preview limits. Prefer **classic** `<script src>` bundles or **one** module entry plus **CDN** libraries — **cross-file** `import './sibling.js'` graphs between generated files are **not** reliably previewed (inline order is merged, but local module edges are not bundled).

For **gallery images**, use **`gallery_strip_image_v1`** only. When KMBL-side generation applies, prefer those artifacts over defaulting to generic placeholder image URLs; when it does not, use **external** (or omit **source** where appropriate) and **never** label **`source`: `generated`** without a genuinely generated image. Avoid making fixed Picsum-style seeded URLs the default for **gallery-varied** runs.
