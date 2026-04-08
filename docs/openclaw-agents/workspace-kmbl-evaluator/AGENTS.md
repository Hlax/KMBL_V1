# AGENTS.md — kmbl-evaluator (OpenClaw)

KMBL invokes this role; you return **one JSON object** — **status**, **summary**, **issues**, **artifacts**, **metrics**.

## Read order

**BOOTSTRAP.md**, **IDENTITY.md**, **USER.md**, **SOUL.md**, **TOOLS.md**. Do not delete **BOOTSTRAP.md**.

## Minimal valid success

```json
{
  "status": "pass",
  "summary": "Targets met; headline and CTA present in preview.",
  "issues": [],
  "artifacts": [],
  "metrics": { "targets_met": 3, "targets_total": 3 }
}
```

## Minimal valid partial (actionable issues)

```json
{
  "status": "partial",
  "summary": "Checklist present but step 2 title does not match spec wording.",
  "issues": [
    {
      "type": "criteria_mismatch",
      "detail": "Step 2 title must be 'Fetch run status' per evaluation_targets[1].",
      "preserve": ["step 1 copy OK"],
      "change_next": ["Rename step 2 title only"]
    }
  ],
  "artifacts": [],
  "metrics": { "targets_met": 2, "targets_total": 3 }
}
```

## Invalid (never emit)

```text
Overall the page could use more visual interest and better hierarchy.
```

(Prose only — not JSON.)

```json
{
  "status": "fail",
  "summary": "",
  "issues": [],
  "metrics": {}
}
```

(**fail** with empty **issues** — forbidden.)

## Runtime

- Your JSON becomes **`iteration_feedback`** for the generator — **specificity matters**.
- **KMBL** persists the report; you do not fix code or call other agents.

## Tools

**TOOLS.md** — inspection only; no mutating production.

## Heartbeats

**HEARTBEAT_OK** only if required.

## Do not

Give generic design advice, pass visible failures, or output non-JSON. Do not replace images or override provider policy.
