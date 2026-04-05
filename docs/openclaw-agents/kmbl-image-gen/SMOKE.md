# SMOKE.md — kmbl-image-gen

Minimal checks that **image intent** routes to **`kmbl-image-gen`**, artifacts are gallery-shaped, and failures are explicit when the Images API is unavailable.

## Scenario

Use orchestrator preset **`kiloclaw_image_only_test_v1`** (seed/tag **`kmbl_kiloclaw_image_only_test_v1`**). It exists so runs **require** gallery images via **KiloClaw** **`kmbl-image-gen`** routing — not orchestrator-side OpenAI Images.

## Orchestrator (routing + contract — no live gateway required)

From repo root (adjust path if needed):

```bash
cd services/orchestrator
pytest tests/test_kilo_model_routing.py -v -k "kiloclaw_image_only or image"
```

Broader orchestrator suite:

```bash
cd services/orchestrator
pytest -q
```

## Graph smoke (HTTP — needs running orchestrator + gateway for a full pixel path)

With orchestrator on port **8010** (default in `smoke_common`):

```bash
cd services/orchestrator
set PYTHONPATH=src
python scripts/run_graph_smoke.py --preset kiloclaw_image_only_test_v1 --port 8010 --no-server
```

(PowerShell: `$env:PYTHONPATH='src'` then `python scripts/run_graph_smoke.py ...`.)

(Use `--no-server` if **uvicorn** is already running; omit it to let the script spawn the server.)

**Full end-to-end** (real **`kmbl-image-gen`** + **`OPENAI_API_KEY`** on gateway): run the same preset against a deployed orchestrator and gateway with **`agents.list`** containing **`kmbl-image-gen`** and a working **`openai-image-gen`** skill. Expect **`routing_metadata_json`** to show **`kiloclaw_image_agent`** / **`provider_config_key`** aligned with **`KILOCLAW_GENERATOR_OPENAI_IMAGE_CONFIG_KEY`**, and **`artifact_outputs`** containing valid **`gallery_strip_image_v1`** rows (success default: **`updated_state`: `{}`**) **or** explicit failure in **`updated_state.kmbl_image_generation`**. **Not** invalid **`ui_gallery_strip_v1`** (e.g. **`surface` / `status` / `item_count` / `model` / `size` / `quality`** without **`items`**).

## Live gateway workspace (VPS sync)

OpenClaw **`workspace`** for **`kmbl-image-gen`** must match this folder. After any **SOUL.md** / instruction change, **re-sync the entire directory** and **restart the gateway** (or reload agents) so the model sees the updated contract.

**Re-sync these files** (repo paths under **`docs/openclaw-agents/kmbl-image-gen/`**):

| File | Purpose |
|------|--------|
| **SOUL.md** | Contract, success/failure shapes, prompt return |
| **USER.md** | Caller / outputs summary |
| **AGENTS.md** | Red lines & first-run |
| **TOOLS.md** | exec / Images API / output rules |
| **BOOTSTRAP.md** | Agent declaration |
| **IDENTITY.md** | Agent id |
| **SMOKE.md** | This smoke doc |
| **HEARTBEAT.md** | Heartbeat policy |
| **MEMORY.MD** | Memory policy |

Copy the **whole folder** to the VPS path referenced in **`openclaw.json`** (or your **`agents.list`** entry **`workspace`**), then restart.

## Gateway (operator)

After merging **`docs/openclaw/kmbl-image-gen.agents-list-entry.json`** and restarting the gateway:

```bash
openclaw agents list
```

Confirm **`kmbl-image-gen`** appears. See **`docs/openclaw/README.md`** for Windows path notes and **`OPENAI_API_KEY`**.
