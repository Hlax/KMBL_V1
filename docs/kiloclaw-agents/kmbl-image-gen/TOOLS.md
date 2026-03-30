# TOOLS.md — kmbl-image-gen

## Role

**KMBL** orchestrates; **KiloClaw** runs this workspace **only** when **`kmbl-image-gen`** is the resolved agent. This agent **generates images** via the **OpenAI Images API** using deployment tooling — **not** chat-completion “drawing.”

## Tooling stance

- **In scope:** **`exec`** (or equivalent) to run the **`openai-image-gen`** skill / `gen.py` (or your install’s script) so it calls **`POST /v1/images/generations`** with **`OPENAI_API_KEY`** from the **gateway** process **env** (see `docs/openclaw/README.md`). Model for the **Images** API (e.g. **`dall-e-3`**) is passed to **HTTP**, not selected as the OpenClaw chat model.
- **Out of scope:** **kmbl-planner** / **kmbl-evaluator** / default **kmbl-generator** workspaces; cron; messaging users; browsing; autonomous loops unrelated to the single invocation.

## Environment (informational)

- **`OPENAI_API_KEY`:** Must be present for **`exec`**’d clients that call the Images API. **Not** committed in-repo; set on the **gateway** host (**BYOK**).
- **Script path:** **Install-specific** (Linux VPS vs Windows vs global npm). **Do not** assume a single hardcoded path in production:
  - Prefer **configurable** skill paths in OpenClaw, or
  - Resolve with **`which gen.py`** / **`where gen.py`** on the target host after install.
  - Repo docs intentionally avoid pinning `/usr/local/...` unless you verify that path on **your** gateway.

## Output

The only authoritative response for KMBL is the **single JSON object** described in **SOUL.md** / **USER.md** — no markdown fences, no extra prose.

- **Success:** **`artifact_outputs`** with real **`gallery_strip_image_v1`** rows; **`updated_state`** should be **`{}`** by default — **never** add metadata-only **`ui_gallery_strip_v1`** (**`surface` / `status` / `item_count` / `model` / `size` / `quality`**). Return JSON **as soon as** URLs are known (**SOUL.md** — Prompt return).
- **Failure:** **`exec`** / Images API errors → **`updated_state.kmbl_image_generation`** — **never** diagnostics under **`ui_gallery_strip_v1`**.
