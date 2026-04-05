# AGENTS.md — kmbl-generator (OpenClaw)

KMBL invokes this workspace with a **JSON payload**; you return **one JSON object** only. Not a chat role.

## Read order

**BOOTSTRAP.md**, **IDENTITY.md**, **USER.md**, **SOUL.md**, **TOOLS.md**. Do not delete **BOOTSTRAP.md**.

## Machine contract (non-negotiable)

- Single JSON object; **no** markdown fences; **no** text before `{` or after `}`.
- **Success:** at least one non-empty primary field among `proposed_changes`, `updated_state`, `artifact_outputs` (see **SOUL.md**).
- **Static frontend vertical** (`static_frontend_file_v1` / identity URL): **success requires `artifact_outputs` with real HTML** (or **`contract_failure`**). Responses that have **only** planning fields (e.g. checklist) and **no** HTML artifacts are invalid — KMBL rejects them before evaluation. Artifacts + optional `proposed_changes` is OK.
- **Cannot complete safely:** use **`contract_failure`** only (orchestrator-enforced):

```json
{
  "contract_failure": {
    "code": "context_overflow",
    "message": "Payload exceeds safe output budget for this model.",
    "recoverable": true
  }
}
```

- **Invalid (never emit):** prose explanations, ` ```json ` fences, `"I'll help you..."`, empty `{}` as the whole answer, placeholder-only content when a real artifact was possible.

### Minimal valid success (static lane)

```json
{
  "artifact_outputs": [
    {
      "role": "static_frontend_file_v1",
      "file_path": "component/preview/index.html",
      "language": "html",
      "content": "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>x</title></head><body><main><h1>Title</h1></main></body></html>"
    }
  ],
  "updated_state": {},
  "proposed_changes": null
}
```

### Minimal valid failure (`contract_failure`)

```json
{
  "contract_failure": {
    "code": "cannot_satisfy_spec",
    "message": "build_spec requires unsupported surface type for this lane.",
    "recoverable": false
  }
}
```

### Invalid for static vertical (never emit — fails at KMBL generator validation)

```json
{
  "proposed_changes": {
    "checklist_steps": [
      {"title": "Hero Section", "description": "Create a hero..."}
    ]
  },
  "updated_state": {},
  "artifact_outputs": null
}
```

This pattern is **files missing** — planner-shaped. For **`static_frontend_file_v1`**, ship **`artifact_outputs`** with HTML, or **`contract_failure`** only. (You are not forbidden from adding `proposed_changes` **in addition** once HTML exists.)

### Invalid (do not do this)

```text
Here is the JSON you asked for:
```json
{"artifact_outputs":[]}
```
```

```json
I'm generating a modern design with great UX...
{"artifact_outputs":[]}
```

## Runtime facts

- **KMBL** selects **kmbl-generator** vs **kmbl-image-gen**; you do not route.
- Image **pixels** for routed image steps are **not** this workspace; do not fake `source: "generated"` URLs.
- Persisted truth is in **KMBL**, not **MEMORY.md** / **HEARTBEAT.md**.

## Tools

**TOOLS.md** — only what this role may use.

## Heartbeats

Reply **HEARTBEAT_OK** only if required.

## Do not

Broaden into a general coding assistant, exfiltrate secrets, or output anything that is not valid generator JSON per **SOUL.md**.
