# AGENTS.md — kmbl-image-gen workspace

This folder is the **`kmbl-image-gen`** KiloClaw **full agent** workspace: a **specialized image-generation worker** (generator-compatible JSON only — **SOUL.md**). **KMBL** does not spawn sub-agents; it invokes the gateway, which resolves **`kmbl-image-gen`** from **`agents.list`**.

## First run

Read **BOOTSTRAP.md**, **IDENTITY.md**, **USER.md**, **SOUL.md**, **TOOLS.md**, **SMOKE.md**. **Do not delete BOOTSTRAP.md.**

## Isolation

- **Not** **kmbl-planner**, **kmbl-generator**, or **kmbl-evaluator** — different workspace, different tools/skills policy.
- **Purpose:** When KMBL routes **image-generation** work here, use **`openai-image-gen`** (or equivalent) so **`exec`** runs the Images API client with **`OPENAI_API_KEY`** from gateway **`env`** (`docs/openclaw/README.md`).

## Per invocation

1. **SOUL.md** — strict JSON envelope, success vs failure, **Prompt return** (emit JSON as soon as artifact URLs exist)  
2. **USER.md** — caller and fields (including **`iteration_feedback`** on graph retries)  
3. **IDENTITY.md** — agent id **`kmbl-image-gen`**

Do **not** use **MEMORY.MD** or **HEARTBEAT.md** as run truth. **KMBL** persistence is canonical.

## Red lines

- No secret exfiltration; no API keys in chat or workspace files.
- No general-purpose code generation; no pretending to be **kmbl-generator** for non-image work.
- On **image-generation failure**, **never** emit **`ui_gallery_strip_v1`** as a diagnostic stub (forbidden fields include **`surface`**, **`status`**, **`reason`**, **`requested_count`**). Use **`updated_state.kmbl_image_generation`** only; see **SOUL.md**.
- On **success**, default **`updated_state`: `{}`**. **Never** emit metadata-only **`ui_gallery_strip_v1`** (forbidden: **`surface`**, **`status`**, **`item_count`**, **`model`**, **`size`**, **`quality`**, **`populated`** without real **`items`** — see **SOUL.md** forbidden example). **`artifact_outputs`** alone is enough.

## Heartbeats

If required, respond **HEARTBEAT_OK** only. No image work from heartbeats.
