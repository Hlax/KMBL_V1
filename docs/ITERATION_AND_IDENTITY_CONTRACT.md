# Iteration plan and identity evolution contract

This document pins the **orchestrator-owned** contract between evaluator output and the next generator/planner invocation. Remote agents (KiloClaw) should treat these fields as **authoritative hints**, not suggestions.

## `iteration_plan` (generator input)

Built in [`runtime/iteration_plan.py`](../services/orchestrator/src/kmbl_orchestrator/runtime/iteration_plan.py) and attached to [`GeneratorRoleInput`](../services/orchestrator/src/kmbl_orchestrator/contracts/role_inputs.py).

| Field | Meaning |
|-------|---------|
| `treat_feedback_as_amendment_plan` | Evaluator issues are the amendment checklist. |
| `pivot_layout_strategy` | True → larger layout/visual change; duplicate, fail, stagnation, rebuild pressure, or very low design rubric on partial. |
| `iteration_strategy` | `"pivot"` or `"refine"`. |
| `evaluator_status` | Last pass/partial/fail. |
| `stagnation_count` / `pressure_recommendation` | From working-staging facts (pressure subsystem). |

Planner prompts in [`docs/kiloclaw-agents/`](./kiloclaw-agents/) should reference `identity_context.facets_json.evolution_signals` and `recent_quality_trend` when choosing **success_criteria** and **evaluation_targets**.

## `evolution_signals` (identity profile)

Written in [`identity/hydrate.py`](../services/orchestrator/src/kmbl_orchestrator/identity/hydrate.py) (`upsert_identity_evolution_signal`) after staging. Each signal includes `evaluation_status`, `evaluation_summary`, `issue_count`, optional `staging_snapshot_id`. Facets also carry `recent_quality_trend` derived from recent statuses.

Planners should **prefer** addressing recurring issues and **respect** improving vs stuck trends when proposing new directions.

## Identity context flags

| Flag | When |
|------|------|
| `is_fallback` | Synthetic default profile used (dev-friendly; disable with `KMBL_IDENTITY_ALLOW_FALLBACK_PROFILE=false`). |
| `identity_unresolved` | No profile/facets and fallback disallowed — planner must not assume a real scrape. |
