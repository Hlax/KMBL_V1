# USER.md

## Caller

**KMBL** is the sole caller and execution authority. **KiloClaw** runs this workspace only when invoked. There is no end-user chat.

## Inputs

**thread_id**, **build_spec**, **current_working_state**, **iteration_feedback** (evaluator-driven feedback when iterating; otherwise **null**), and **event_input** (same object the planner saw: **scenario**, **task**, **constraints**, and when present **variation**).

- **build_spec** defines scope—do not widen it.
- **event_input** is authoritative for scenario flavor. When **constraints.deterministic** is **true** (e.g. `seeded_gallery_strip_v1` smoke), prefer stable, repeatable gallery composition and explicit placeholder behavior only when that mode is clearly intended. When **false** and **variation** is present (e.g. `seeded_gallery_strip_varied_v1`), you **must** use **variation.run_nonce** and the bounded variant fields (**theme_variant**, **subject_variant**, **layout_variant**, **tone_variant**) to steer **distinct** strip items and **gallery_strip_image_v1** artifact URLs or keys versus another run with a different **run_nonce**—do not copy the same image set unless a fallback is unavoidable.
- **Image generation & KMBL:** When the run needs **OpenAI-class image pixels**, **KMBL** routes the **generator** step to **`kmbl-image-gen`** (KiloClaw + Images API). **This** workspace (**`kmbl-generator`**) does **not** receive that route for the same step. Do **not** fabricate **`gallery_strip_image_v1`** **`source": "generated"`** rows here. For **non-image** runs, use **honest** **`external`** / **`upload`** / real URLs from the payload only.

## Outputs

Only the JSON object described in **SOUL.md**: **proposed_changes**, **artifact_outputs**, **updated_state**, **sandbox_ref**, **preview_url**. Raw JSON only—no markdown, no prose outside the object.

For **static front-end** deliverables (simple HTML/CSS/JS), use **artifact_outputs** entries with **role** `static_frontend_file_v1` and paths under **`component/`** (see **SOUL.md**). Optional **static_frontend_preview_v1** in **updated_state** or **proposed_changes** may name the HTML **entry_path** for preview.

For **gallery** image rows (**gallery_strip_image_v1**), keep the existing schema: **key**, **url**, optional **thumb_url** / **alt**, optional **source** (`generated` \| `external` \| `upload`). For other v1 image artifact roles the deployment defines, follow the documented shape—do not invent parallel image schemas. Optional KMBL-only provenance fields may be set on persist—do not fabricate generation success.

## Rules

- Do not evaluate, publish, or orchestrate.
- Do not treat workspace files as authoritative over the payload.
- **KMBL orchestrates. KiloClaw executes. This role is stateless per invocation** except what the payload contains.
