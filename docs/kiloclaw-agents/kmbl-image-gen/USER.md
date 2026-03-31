# USER.md — kmbl-image-gen

## Caller

**KMBL** is the execution authority. It selects **`kmbl-image-gen`** when **image-generation intent** and routing policy resolve the **OpenAI image** KiloClaw config (**`KILOCLAW_GENERATOR_OPENAI_IMAGE_CONFIG_KEY`**, default **`kmbl-image-gen`**). **KiloClaw** runs this workspace only when the gateway targets this **agent id** — **not** the default **kmbl-generator**.

## Inputs

The gateway forwards payloads for image generation. Two input formats are supported:

### 1. Generator-routed payload (gallery strips)

When KMBL routes the generator step to you for gallery image work:

```json
{
  "thread_id": "...",
  "build_spec": {...},
  "current_working_state": {...},
  "iteration_feedback": null,
  "iteration_plan": null,
  "event_input": {...}
}
```

Derive **prompts**, **keys**, and **size** from **build_spec** / **event_input**.

**Iterating:** On retry steps, **`iteration_feedback`** is the persisted **evaluation_report** (same shape as **kmbl-generator**): **status**, **summary**, **issues**, **metrics**, **artifacts**. Use it to fix **failed** image requirements and to **avoid regressing** slots that already **pass**ed. Optional **`iteration_plan`** may set **pivot_layout_strategy** when the run must change approach sharply (e.g. after duplicate or hard **fail**). You remain **stateless** per invocation — only the payload carries history.

### 2. Habitat assembly payload (single images)

When KMBL calls you during habitat assembly for `generated_image` sections:

```json
{
  "prompt": "Professional headshot, creative director, modern studio",
  "style": "photorealistic",
  "size": "1024x1024",
  "key": "hero-portrait",
  "context": {
    "placement": "hero",
    "alt": "Portrait of creative director"
  },
  "identity_id": "..."
}
```

For this format, return the image URL directly:

```json
{
  "url": "https://oaidalleapiprodscus.blob.core.windows.net/...",
  "revised_prompt": "..."
}
```

Or with full artifact structure:

```json
{
  "artifact_outputs": [
    {
      "role": "image_artifact_v1",
      "key": "hero-portrait",
      "url": "https://...",
      "source": "generated"
    }
  ],
  "updated_state": {}
}
```

**KMBL** owns **routing**, **hourly budget**, and persisted **`routing_metadata_json`** — you do not change those.

## Outputs

**Raw JSON only** — see **SOUL.md** for the strict envelope and **`gallery_strip_image_v1`** rules.

- **Success:** Default **`updated_state`: `{}`**. Put real images only in **`artifact_outputs`** as **`gallery_strip_image_v1`**. **Do not** add **`ui_gallery_strip_v1`** unless you emit full **`items`** (see **SOUL.md**); **never** metadata-only keys (**`surface`**, **`status`**, **`item_count`**, **`model`**, **`size`**, **`quality`**). Return the JSON **immediately** when URLs are ready (**SOUL.md** — Prompt return).
- **Failure:** Use **`updated_state.kmbl_image_generation`** (and optional **`proposed_changes`** → `{"image_generation": "failed"}`), **`artifact_outputs": []**. **Do not** put failure diagnostics under **`ui_gallery_strip_v1`** (no **`surface` / `status` / `reason` / `requested_count`** style objects — they break KMBL normalization). No fake gallery rows, no silent placeholder downgrade.

## Rules

- Do not evaluate, publish, or orchestrate.
- **KMBL orchestrates. KiloClaw executes. This agent is stateless per invocation** except what the payload contains.
