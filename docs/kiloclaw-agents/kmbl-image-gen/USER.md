# USER.md — kmbl-image-gen

## Caller

**KMBL** is the execution authority. It selects **`kmbl-image-gen`** when **image-generation intent** and routing policy resolve the **OpenAI image** KiloClaw config (**`KILOCLAW_GENERATOR_OPENAI_IMAGE_CONFIG_KEY`**, default **`kmbl-image-gen`**). **KiloClaw** runs this workspace only when the gateway targets this **agent id** — **not** the default **kmbl-generator**.

## Inputs

The gateway forwards the **generator** payload KMBL built for the graph step (or a documented subset). Expect fields consistent with **GeneratorRoleInput**: **thread_id**, **build_spec**, **current_working_state**, **iteration_feedback**, **event_input**.

- Derive **prompts**, **keys**, and **size** from **build_spec** / **event_input** — **do not** widen scope.
- **KMBL** owns **routing**, **hourly budget**, and persisted **`routing_metadata_json`** — you do not change those.

## Outputs

**Raw JSON only** — see **SOUL.md** for the strict envelope and **`gallery_strip_image_v1`** rules.

- **Success:** Default **`updated_state`: `{}`**. Put real images only in **`artifact_outputs`** as **`gallery_strip_image_v1`**. **Do not** add **`ui_gallery_strip_v1`** unless you emit full **`items`** (see **SOUL.md**); **never** metadata-only keys (**`surface`**, **`status`**, **`item_count`**, **`model`**, **`size`**, **`quality`**). Return the JSON **immediately** when URLs are ready (**SOUL.md** — Prompt return).
- **Failure:** Use **`updated_state.kmbl_image_generation`** (and optional **`proposed_changes`** → `{"image_generation": "failed"}`), **`artifact_outputs": []**. **Do not** put failure diagnostics under **`ui_gallery_strip_v1`** (no **`surface` / `status` / `reason` / `requested_count`** style objects — they break KMBL normalization). No fake gallery rows, no silent placeholder downgrade.

## Rules

- Do not evaluate, publish, or orchestrate.
- **KMBL orchestrates. KiloClaw executes. This agent is stateless per invocation** except what the payload contains.
