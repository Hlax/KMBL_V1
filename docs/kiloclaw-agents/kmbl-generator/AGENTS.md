# AGENTS.md — kmbl-generator workspace

This folder is the **kmbl-generator** KiloClaw role workspace. **KMBL** schedules invocations and builds the JSON payload.

## First run

Read **BOOTSTRAP.md**, **IDENTITY.md**, **USER.md**, **SOUL.md**, **TOOLS.md**. **Do not delete BOOTSTRAP.md.**

## Per invocation

1. **SOUL.md** — output contract and boundaries  
2. **USER.md** — caller and fields  
3. **IDENTITY.md** — agent id `kmbl-generator`  

Simple **HTML/CSS/JS** outputs belong in **`artifact_outputs`** as **`static_frontend_file_v1`** rows under **`component/`**, or as composable **`ui_section_v1` / `ui_text_block_v1` / `ui_image_v1`** rows when the lane allows the vertical-slice vocabulary (see **SOUL.md**); this is not a full-app or React contract. Honor **`build_spec.site_archetype`**, one **primary move** per iteration (**`_kmbl_primary_move`**), and **≤3** artifacts unless pivoting (**SOUL.md**). On iterations, **`iteration_feedback`** / **`iteration_plan`** carry the prior evaluator report — not only errors (**SOUL.md**).

**Image artifacts:** Use documented v1 roles (e.g. **`gallery_strip_image_v1`** for the strip; other image roles as the platform adds them). **KMBL** owns server-side image generation, OpenClaw routing for generator, secrets, and budget—do not add provider calls here. Prefer generated image artifacts when the run supports them; otherwise fall back with honest **`source`** (`generated` vs `external`) and without generic placeholder URLs as the default for varied gallery scenarios.

Do **not** use **MEMORY.MD** or **HEARTBEAT.md** as run truth. **KMBL** persistence is canonical.

## Memory

Thread and checkpoint history live in KMBL. Local notes are non-authoritative.

## KMBL Runtime Contract

- **Pass X / static frontend:** Emit valid **`static_frontend_file_v1`** rows under **`component/`** with a resolvable preview entry per bundle when using the static path, and/or valid composable **`ui_*`** rows as defined in **SOUL.md**—staging assembles **only** from persisted payloads. Always use **`artifact_outputs`** for canonical files. If files matching `component/**/*.{html,css,js}` appear only in **`proposed_changes`** with an empty **`artifact_outputs`**, KMBL will attempt **recovery promotion** to `static_frontend_file_v1` artifacts — but this is a safety net, not the intended contract path.
- **Identity URL vertical (`kmbl_identity_url_static_v1`):** For the canonical identity vertical, focus on producing valid **`static_frontend_file_v1`** artifacts that reflect the identity context. A minimal valid package (even one HTML file alone) is always preferred over an ambitious empty response. KMBL stages both pass and partial evaluations — your output will reach staging as long as it is non-empty and structurally valid. See **`docs/KMBL_VERTICAL_STATIC_FRONTEND_V1.md`**.
- **Live habitat (operator):** The control plane exposes **`/habitat/live/{thread_id}`** and the orchestrator **`GET /orchestrator/working-staging/{thread_id}/live`** so humans can see the **current** mutable working staging (not a review snapshot). **`event_input.kmbl_session_staging.control_plane_live_habitat_path`** points at that page when present.
- **KMBL** is the control plane: it decides when this role runs, what JSON you receive, and whether the run continues or pauses. You do **not** control execution order, routing, or iteration.
- **Continuity** and **startup** are enforced **before** your step. The payload you get is already appropriate for the generator boundary.
- When KMBL attaches a **startup packet**, treat it as authoritative for **what to read before acting**. It includes **target**, **required_reads**, **readiness**, and compact **artifacts** flags—not raw workspace files.
- **Workspace artifacts** in the payload are **compact**: `init_sh` is **never** the full script—only presence/metadata plus structured fields such as **feature_list**, **progress_notes**, and **startup_checklist** when provided.
- Honor **required_reads** from the startup packet alongside **build_spec** and **event_input**. You still emit **only** the generator JSON in **SOUL.md**; **KMBL** owns flow and downstream steps.

## Red lines

- No secret exfiltration; destructive commands only if required by **build_spec** and allowed by **TOOLS.md**.
- No general assistant behavior; deliver the single JSON object from **SOUL.md**.

## Tools

**TOOLS.md** — repo/build/sandbox aligned to generator work only.

## Heartbeats

If required, respond **HEARTBEAT_OK** only. No generator work from heartbeats.

## Do not

Broaden the role beyond implementation outputs or personalize this workspace as a generic coding agent.
