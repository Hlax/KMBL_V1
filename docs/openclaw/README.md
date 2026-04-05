# OpenClaw gateway — `kmbl-image-gen` (repo scaffold)

**Secrets:** Do **not** commit live API keys, Discord tokens, gateway auth tokens, or Stream Chat credentials. Use **`openclaw.json.example`** as the safe template; copy it to a **local** `openclaw.json` (or merge into your gateway host config) and fill values **only on the machine** that runs the gateway. If real secrets were ever committed to git, **rotate them** in each provider’s dashboard—git history may retain old values.

## Chat models (planner / generator / evaluator)

**KMBL does not choose the LLM.** The orchestrator only sends OpenAI-style chat requests with `model: "openclaw:<agent_id>"` (e.g. `openclaw:kmbl-planner`). The OpenClaw gateway resolves that **agent id** to a concrete backend model using **`~/.openclaw/openclaw.json`**.

**Reference:** **`openclaw.json`** and **`openclaw.json.example`** in this folder track the current layout (gateway **port 18789**, loopback, Ollama **`models.providers`**, `kmbl-*` agents with **`workspace`** / **`agentDir`**). Paths use **`C:\Users\<you>\`** placeholders where not otherwise pinned; replace with your profile. **Secrets are redacted** (`<gateway-auth-token>`, placeholder Tailscale origin)—never commit real tokens.

### `kmbl-generator` workspace (local-build + orchestrator ingest)

See **`WORKSPACE_ALIGNMENT.md`** for the full **`agentDir` vs `workspace`** table and **`KMBL_GENERATOR_WORKSPACE_ROOT`** rules.

- **Repo reference:** **`openclaw.json`** uses **`C:\Users\<you>\.openclaw\workspace-kmbl-generator`** (or merge **`kmbl-generator.agents-list-entry.json`** with `~/.openclaw/...` expanded on your OS). **Not** a universal path — set the real absolute path only on the gateway host.
- **Orchestrator:** Set **`KMBL_GENERATOR_WORKSPACE_ROOT`** to the **same** absolute path as OpenClaw **`kmbl-generator.workspace`** (e.g. in repo root **`.env.local`**, not committed). Then ingest and **`sandbox_ref`** validation match.
- **Do not** point OpenClaw **`workspace`** at the KMBL **application git checkout**; keep the build sandbox separate from **`KMBL_V1`** source.

**Model resolution:** **`agents.defaults.model.primary`** applies when an agent has no **`model`** block. Per-agent **`model.primary`** overrides. In the checked-in reference, **`kmbl-planner`** inherits the default (**`ollama/qwen2.5-coder:7b`**); **`kmbl-generator`** and **`kmbl-evaluator`** override with **`ollama/mistral:latest`**. After edits, **restart the OpenClaw gateway** and confirm in the TUI which **`ollama/...`** each agent uses.

### KMBL repo agent instructions vs runtime

**Changing planner/generator behavior:** Updates live in **`docs/openclaw-agents/kmbl-planner/`** and **`docs/openclaw-agents/kmbl-generator/`** (e.g. **SOUL.md**, **USER.md**) are **not** picked up by the gateway until they are **copied or symlinked** into each agent’s **`agentDir`** under **`~/.openclaw/agents/...`** (see **`agents.list[].agentDir`** in **`openclaw.json`**). **`openclaw.json` itself usually does not need edits** for instruction-only changes — the operational step is **sync markdown → agent workspace → restart gateway**. If you change **models** or **paths**, then edit JSON and restart.

### KMBL graph runs vs OpenClaw chat (why chat can “pass” while the run fails)

- **OpenClaw chat / TUI** is a conversational loop with its own session; success means the model replied usefully. It does **not** enforce KMBL’s **JSON contracts** for planner / generator / evaluator or persist **Supabase** rows.
- **KMBL** calls the gateway with **`model: openclaw:`** + agent id and expects **parseable JSON** in **`message.content`** per role, then runs **staging** and DB writes. Failures are often **`provider_error`** (timeouts, 401), **`contract_validation`**, or **graph** errors—not “the model was wrong in chat.”
- **Per-run session isolation:** the orchestrator sends **`user`** = `kmbl-orchestrator:{thread_id}:{graph_run_id}` so gateway session state does not match a **chat-only** session key.
- **Operator debugging:** **`GET /orchestrator/runs?thread_id={uuid}`** lists runs for one thread (newest first). Then **`GET /orchestrator/runs/{graph_run_id}`** for **`failure_phase`**, **`error_message`**, and **`timeline_events`**.

**Observed failure modes (example thread `99f654f9-a62a-495d-aaf2-74be26cb608f`):**

| Symptom in `GET /orchestrator/runs/{id}` | Likely cause |
|------------------------------------------|----------------|
| **`TimeoutError: Could not acquire thread lock … within 300s`**, **`role_invocation_count`: 0** | Another graph or lock holder on the **same thread**; avoid overlapping starts or wait for the prior run to finish / release. |
| **`failure_phase`: `evaluator`**, **`ReadTimeout`**, “gateway failed after 3 attempts: timed out” | **HTTP read timeout** to OpenClaw (evaluator slow or stalled). Raise **`OPENCLAW_HTTP_READ_TIMEOUT_SEC`**, reduce load, or fix gateway/Ollama latency—not a “wrong model in chat” issue. |

This folder holds a **mergeable** `agents.list` entry for the **`kmbl-image-gen`** full agent. **KMBL** is unchanged here; set **`KILOCLAW_GENERATOR_OPENAI_IMAGE_CONFIG_KEY=kmbl-image-gen`** on the orchestrator when you wire routing.

**Operator visibility (KMBL control plane):** The mutable **working staging** surface for a thread is viewable as **live habitat** at **`/habitat/live/{thread_id}`** (same assembled HTML as the orchestrator preview, not a review snapshot). Session staging links in graph run payloads include **`control_plane_live_habitat_path`**. This is independent of OpenClaw agent workspaces; it only needs the orchestrator + control plane apps running.

## Where to add it

In your **live** OpenClaw gateway config (commonly `openclaw.json` on the gateway host):

1. Find the **`agents`** (or equivalent) section that contains **`list`** (array of agent definitions).
2. **Append** the JSON object from **`kmbl-image-gen.agents-list-entry.json`** to that array (or merge fields if your schema nests differently).

Exact key names (`agents.list` vs `agents` → `list`) depend on your OpenClaw version — use the same shape as existing **`kmbl-generator`** / **`kmbl-planner`** entries.

## Workspace path on disk

- **Repo (source):** `docs/openclaw-agents/kmbl-image-gen/` — markdown workspace for review and copy.
- **Runtime:** Copy or symlink that folder to the path you set as **`workspace`** in the JSON entry (example below uses `~/.openclaw/workspace-kmbl-image-gen`).

### Windows path assumptions

- **`~`** may **not** expand the same way in all tools. Prefer an **absolute** path in `openclaw.json`, e.g.  
  `C:\\Users\\<you>\\.openclaw\\workspace-kmbl-image-gen`  
  or `%USERPROFILE%\.openclaw\workspace-kmbl-image-gen` resolved to a string in JSON.
- **`openai-image-gen`** script paths (e.g. under `node_modules`) differ by install — set **`exec`** / skill paths per your machine (see **`docs/openclaw-agents/kmbl-image-gen/TOOLS.md`**).

## Auth paths (why KiloCode BYOK ≠ `gen.py`)

| Path | What it is | Credential |
|------|------------|------------|
| **OpenClaw chat model** (e.g. `kilocode/...`, `openai/...`) | Text LLM — chat completions / Responses | Provider / KiloCode / gateway auth as **your** stack configures |
| **`openai-image-gen` / `gen.py`** | **HTTP** `POST https://api.openai.com/v1/images/generations` | **`OPENAI_API_KEY`** on the **gateway process** — read from **`env`** (e.g. `openclaw.json` → `env`) or the OS environment before start |

`gen.py` does **not** read KiloCode BYOK profiles; it only sees whatever **`exec`** inherits. **`dall-e-3`** is passed to the **Images API**, not selected as an OpenClaw “chat model.”

## `OPENAI_API_KEY` (gateway — not in this git repo)

**Yes, you can set it in `openclaw.json`** under top-level **`env`** — **on the gateway host only.**

**Do not** paste keys into **`docs/openclaw/`** or commit a real `openclaw.json` with secrets into **KMBL**. Treat gateway config like production: gitignore local overrides, or use machine env vars / a secret store.

**Proceed without a key:** You can still merge **`kmbl-image-gen.agents-list-entry.json`**, copy the workspace, set **skills / `tools.deny`**, and restart the gateway. **`gen.py`** will not successfully call OpenAI until **`OPENAI_API_KEY`** is present for that process — that is expected.

**KMBL orchestrator image pixels:** Production runs route the **generator** to **`kmbl-image-gen`** via **`KILOCLAW_GENERATOR_OPENAI_IMAGE_CONFIG_KEY`** (see orchestrator `kilo_model_routing`). The orchestrator does **not** call OpenAI Images directly; **`OPENAI_API_KEY`** on the **gateway** powers **`gen.py`**. Legacy **`KMB_OPENAI_IMAGE_API_KEY`** / **`KMB_LEGACY_ORCHESTRATOR_OPENAI_IMAGES`** exist only for narrow tests and stay off by default.

## JSON contract for **`kmbl-image-gen`**

Runtime model output must be **one JSON object** (no markdown fences). Field-level rules and success/failure examples live in **`docs/openclaw-agents/kmbl-image-gen/SOUL.md`** (appendix). **`gallery_strip_image_v1`** rows must match KMBL’s **`GalleryStripImageArtifactV1`** (orchestrator `gallery_image_artifact_v1.py`). On **failure** (no valid images), use **`updated_state.kmbl_image_generation`** — **do not** emit a partial **`ui_gallery_strip_v1`** (KMBL validates **`UIGalleryStripV1`** and will reject diagnostic stubs). On **success**, prefer **`artifact_outputs`** + **`updated_state`: `{}`**. **`ui_gallery_strip_v1`** is optional and must match **`headline`** + **`items`** — **never** metadata-only objects (**`surface`**, **`status`**, **`item_count`**, **`model`**, **`size`**, **`quality`**).

## Confirm the gateway sees `kmbl-image-gen`

After editing config and **restarting the gateway**:

```bash
openclaw agents list
```

If your CLI supports bindings:

```bash
openclaw agents list --bindings
```

You should see **`kmbl-image-gen`** in the list.

**HTTP check (optional):** `GET` your gateway’s agent listing or health endpoint if documented; otherwise rely on the CLI.

PowerShell (example — adjust host/port/token):

```powershell
curl.exe -s http://127.0.0.1:3001/v1/models `
  -H "Authorization: Bearer $env:KILOCLAW_API_KEY"
```

(Only if your gateway exposes models/agents that way; many installs use the **OpenClaw CLI** as the source of truth.)

## `OPENAI_API_KEY` on the gateway process (verify safely)

**401 `invalid_api_key`** from `api.openai.com` means the HTTP client (`openai-image-gen` / `gen.py`) sent a string OpenAI rejected — not “missing network.” Typical causes: **wrong variable** (e.g. pasted `KILOCLAW_API_KEY` into `OPENAI_API_KEY`), **placeholder** (`sk-...`, `your-key-here`), **unexpanded** `${OPENAI_API_KEY}` in a shell one-liner, **leading/trailing whitespace/newlines** in JSON, **revoked/expired** key, or **key from a different provider** copied by mistake.

**Where it is set:** Whatever starts the gateway must put `OPENAI_API_KEY` in that process’s environment — commonly:

- Top-level **`env`** in **`openclaw.json`** (or your OpenClaw config path), or
- **`Environment=` / `EnvironmentFile=`** in **systemd** unit, or
- **`env:`** in **Docker Compose**, or
- **`export OPENAI_API_KEY=...`** in the **shell script** that launches the gateway (must be **before** `exec`).

`gen.py` does **not** read KiloCode BYOK; it only inherits the gateway **OS env** for the **`exec`** child.

### Linux — check presence and length only (no full secret)

Replace `PID` with the gateway PID (`pgrep -af openclaw`, or `ss -tlnp` on your listen port).

```bash
PID=<gateway_pid>
tr '\0' '\n' < /proc/$PID/environ | awk -F= '$1=="OPENAI_API_KEY"{print "OPENAI_API_KEY length=" length($2)}'
```

If there is no line, the variable is **absent**. If `length=0`, it is **empty**.

### After changing the key

Restart however you start OpenClaw (examples):

```bash
sudo systemctl restart openclaw-gateway   # unit name varies
# or
pm2 restart openclaw
# or: stop the foreground process and start again from the same host
```

### Rerun KMBL smoke (from a dev machine)

```bash
cd services/orchestrator
export PYTHONPATH=src
python scripts/run_graph_smoke.py --preset kiloclaw_image_only_test_v1 --port 8010
```

**Expected after a valid key:** generator completes with real **`gallery_strip_image_v1`** URLs (or honest structured failure JSON if you intentionally disable images), graph reaches **evaluator**; no **401** in gateway logs for Images API.
