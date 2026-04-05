# OpenClaw agent reference docs (KMBL)

Source-of-truth markdown for **`kmbl-planner`**, **`kmbl-generator`**, **`kmbl-evaluator`**, and **`kmbl-image-gen`**. Copy or sync into each agent’s OpenClaw workspace (`~/.openclaw/agents/<id>/`); the orchestrator does not read these files at runtime.

## Tuning order (do this in sequence)

1. **AGENTS.md** (per agent) — contracts, boundaries, what is forbidden.
2. **SOUL.md** — identity and non‑negotiable behavior.
3. **Examples** — minimal valid JSON and invalid examples (short).
4. **Task prompts** — small, run-specific templates only.
5. **Orchestrator** — Pydantic wire contracts in `services/orchestrator/.../contracts/role_outputs.py` catch drift; generator can emit **`contract_failure`** (see below).

## Wire contracts (orchestrator-enforced)

| Role | Input | Output must include |
|------|--------|---------------------|
| Planner | `PlannerRoleInput` (see `role_inputs.py`) | `build_spec`, `constraints`, `success_criteria`, `evaluation_targets` — use **`constraints.variation_levers`** for explicit design controls |
| Generator | `GeneratorRoleInput` | At least one non-empty **`proposed_changes`**, **`updated_state`**, or **`artifact_outputs`** — **or** **`contract_failure`** |
| Evaluator | `EvaluatorRoleInput` | `status` ∈ pass/partial/fail/blocked; structured `issues`, `summary`, etc. |

### Structured failure (generator)

If the model cannot produce artifacts, it must return **JSON only** with:

```json
{
  "contract_failure": {
    "code": "snake_case_machine_code",
    "message": "Short human-readable reason",
    "recoverable": true
  }
}
```

No markdown fences, no preamble, no chat outside this object. The orchestrator maps this to a failed generator phase with **`error_kind`: `contract_failure`**.

### Non‑negotiable style (all roles)

- **No** markdown code fences in the final assistant JSON.
- **No** preamble (“Here is…”), apologies, or conversational filler outside the schema.
- **Uncertainty** → structured failure JSON (planner/generator/evaluator each have a defined shape; generator uses **`contract_failure`**).

## Small-model / local Ollama mode

Tune prompts for the **weakest** model you run in prod (e.g. local Mistral): short planner plans, one surface per generator turn, minimal copy, shallow variation, evaluator issues that are **specific and actionable** (not “make it more engaging”).

Widen lanes only after a stronger model (e.g. GLM flash) is actually available in Ollama.

## Instrumentation

The orchestrator logs **`generator_payload`** / **`generator_invoke`** with **`payload_json_chars`** (serialized generator input size) and elapsed time — use logs to spot prompt bloat before changing code again.

## See also

- Repo root **README** — architecture overview.
- `docs/openclaw/README.md` — gateway and image-gen notes.
