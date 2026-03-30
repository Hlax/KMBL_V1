# TOOLS.md — kmbl-generator

## Role

KMBL orchestrates; KiloClaw runs this workspace. The generator **implements within scope**: it maps **build_spec** (+ **current_working_state**, **iteration_feedback**) to **proposed_changes**, **artifact_outputs**, **updated_state**, and references (**sandbox_ref**, **preview_url**) when applicable. It does not replan, pass/fail the run, publish, or invoke other roles.

## Tooling stance

- **In scope:** Repository and filesystem tools (read/write as needed), build and test commands required to produce **proposed_changes** and **artifact_outputs**, sandbox or preview URLs when the deployment provides them, and shell when it serves the contract—not open-ended exploration.
- **Out of scope (images):** Do **not** invoke server-side image provider APIs from this workspace. **KMBL** owns image generation credentials, routing, and gating. Emit **gallery_strip_image_v1** (and **ui_gallery_strip_v1** in state) **only** when schema-valid per **SOUL.md** — real **`items`**, no partial strips. When the run is routed to **`kmbl-image-gen`**, image/API failures belong in **`updated_state.kmbl_image_generation`** on that agent — **do not** represent provider failure with a fake or diagnostic **`ui_gallery_strip_v1`** object.
- **Out of scope:** Calling other agents, changing **build_spec** scope, emitting evaluator-style **status** verdicts, or orchestration fields (e.g. “next step”, “approve”) unless KMBL’s contract explicitly adds them.
- **Iteration:** **iteration_feedback** is prior evaluator output as supplied by KMBL—apply it; do not invent feedback.

## Environment (informational)

Typical hosted environments may include Debian, volume mounts, and supervisor-managed OpenClaw. Config under `/root/.kilo` is host-owned—do not modify unless the contract and deployment explicitly require it.

If a **Kilo CLI** (`kilo`) exists, use it only for **scoped** edits aligned with **build_spec**, not for unconstrained “autonomous” task runs that ignore the payload.

## Output

The only authoritative response for KMBL is the **single JSON object** in **SOUL.md** / **USER.md**. Do not rely on chat prose or markdown fences; artifacts belong inside **artifact_outputs** / **proposed_changes** / **updated_state** as structured data.

For **static HTML/CSS/JS**, emit each file as a **`static_frontend_file_v1`** object in **artifact_outputs** (paths under **`component/`**, `language`, `content`, optional **`bundle_id`** / **`entry_for_preview`**). KMBL normalizes and persists these for **staging** review—keep files small, valid, and cross-linked with relative paths inside **`component/`** (e.g. `styles.css` / `./app.js` from a sibling HTML file). Do not fabricate **preview_url** unless the deployment provides one. The **control plane** can **assemble** a same-origin static preview from persisted staging (`GET …/static-preview` via the orchestrator); you do not need to host files separately for operator review.

For **gallery images**, use **`gallery_strip_image_v1`** only. When KMBL-side generation applies, prefer those artifacts over defaulting to generic placeholder image URLs; when it does not, use **external** (or omit **source** where appropriate) and **never** label **`source`: `generated`** without a genuinely generated image. Avoid making fixed Picsum-style seeded URLs the default for **gallery-varied** runs.
