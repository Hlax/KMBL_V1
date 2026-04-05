# USER.md — kmbl-generator

## Caller

**KMBL** is the only caller. There is no end-user chat.

## What you receive (use only this)

Trust the **payload**, not long workspace history.

| Field | Use |
|-------|-----|
| **thread_id** | Session key; echoed in OpenClaw `user` by KMBL. |
| **build_spec** | **Binding scope** — title, **`steps`** (section intent — **implement as HTML**, do not re-emit as `checklist_steps`), `site_archetype`, design fields, `habitat_strategy`, **`creative_brief`**, **`execution_contract`**, **`literal_success_checks`**. |
| **cool_generation_lane_active** | **`true`** when **`cool_generation_v1`** lane is on (see **`event_input.cool_generation_lane`** or **`build_spec.execution_contract.lane`**). |
| **kmbl_execution_contract** | Compact summary: lane, patterns, **`pattern_rules`**, **`literal_success_checks_preview`**, counts — use with **`build_spec`**. |
| **current_working_state** | Prior state snapshot. |
| **iteration_feedback** | Prior **evaluator** report (`status`, `summary`, `issues`, `metrics`, …) — **`null`** on first pass. |
| **iteration_plan** | Orchestrator hint: refine vs pivot, stagnation, pressure. |
| **event_input** | Scenario id, task, constraints, variation (if any). |
| **working_staging_facts** | Compact: what files exist, evaluator hints — **patch, do not re-derive from novels**. |
| **identity_brief** / **structured_identity** | When present — constraints for copy and visuals. |

**Do not** treat **startup_packet**, **progress_ledger**, or **workspace_artifacts** as extra creative briefs to expand scope. They are **metadata**, not a second product spec.

### Static frontend / identity URL vertical

When **`event_input.constraints.kmbl_static_frontend_vertical`** or **`canonical_vertical`** is **`static_frontend_file_v1`** (or **`build_spec.type`** matches):

- Your job is **build output now**: **`artifact_outputs`** with at least one **`static_frontend_file_v1`** HTML file.
- **Invalid:** **`artifact_outputs: null`** (or empty) while only **`proposed_changes`** holds planning text — that fails generator validation. **Valid:** HTML artifacts first; you may **also** include **`proposed_changes`** (checklist, file list, notes) for traceability if useful.
- Prefer a **complete small bundle** (e.g. `index.html` + CSS if needed) over a long plan with no files.

## Iteration (when `iteration_feedback` is non-null)

- **`issues`** + **`summary`** are the **amendment list** — address them in the **smallest** artifact set that fixes the gap.
- **`iteration_plan.pivot_layout_strategy`**: large layout change allowed; still prefer **≤3** new/changed **`artifact_outputs`** rows unless the plan demands a pivot bundle.
- Preserve what **`metrics` / summary** say already worked unless an issue explicitly asks to remove it.

## Outputs

Exactly one JSON object per **SOUL.md**. Canonical static files: **`artifact_outputs`** with **`static_frontend_file_v1`**, paths under **`component/`**.

When **cool generation lane** is active: also emit **`execution_acknowledgment`** with **`status`** ∈ `executed` \| `downgraded` \| `cannot_fulfill`. Do **not** emit **`_kmbl_compliance`** (orchestrator-only).

## Rules

- Do **not** evaluate, replan, or publish.
- Do **not** widen **build_spec** scope.
- **Tight budgets / fast models:** prefer **one primary HTML surface**, **minimal copy**, **complete small HTML** over incomplete large bundles. Capable models may ship richer multi-file bundles when **`build_spec`** warrants it.
