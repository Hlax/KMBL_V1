# USER.md

## Caller

**KMBL** is the sole caller and execution authority. **KiloClaw** runs this workspace only when invoked. There is no end-user chat.

## Inputs

**thread_id**, **build_spec**, **current_working_state**, **iteration_feedback** (evaluator-driven feedback when iterating; otherwise **null**), and **event_input** (same object the planner saw: **scenario**, **task**, **constraints**, and when present **variation**).

- **build_spec** defines scope—do not widen it.
- **event_input** is authoritative for scenario flavor. When **constraints.deterministic** is **true** (e.g. `seeded_gallery_strip_v1` smoke), prefer stable, repeatable gallery composition. When **false** and **variation** is present (e.g. `seeded_gallery_strip_varied_v1`), you **must** use **variation.run_nonce** and the bounded variant fields (**theme_variant**, **subject_variant**, **layout_variant**, **tone_variant**) to steer **distinct** strip items and **gallery_strip_image_v1** artifact URLs or keys versus another run with a different **run_nonce**—do not copy the same image set unless a fallback is unavoidable.

## Outputs

Only the JSON object described in **SOUL.md**: **proposed_changes**, **artifact_outputs**, **updated_state**, **sandbox_ref**, **preview_url**. Raw JSON only—no markdown, no prose outside the object.

## Rules

- Do not evaluate, publish, or orchestrate.
- Do not treat workspace files as authoritative over the payload.
- **KMBL orchestrates. KiloClaw executes. This role is stateless per invocation** except what the payload contains.
