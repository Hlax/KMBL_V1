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
| `issue_count` | Count of **actionable quality issues only** — grounding issues are stripped before this count is computed. |
| `grounding_only_partial` | `True` when the evaluator partial was caused solely by the demo preview grounding gate (build quality was pass; no generator retry will be issued). |
| `stagnation_count` / `pressure_recommendation` | From working-staging facts (pressure subsystem). |

### Grounding issue stripping

`build_iteration_plan_for_generator` strips issues with `code == "demo_preview_grounding_not_satisfied"` before computing `issue_count`. This prevents the grounding infrastructure gap from inflating the issue count or triggering a pivot.

When `grounding_only_partial` is `True`, `issue_count` will be 0 and `iteration_strategy` will be `"refine"` — but `decision_router` routes to `stage` (degraded) before the generator is ever called. See [`19_EVALUATOR_DECISION_POLICY.md`](19_EVALUATOR_DECISION_POLICY.md).

`sanitize_feedback_for_generator` (`runtime/demo_preview_grounding.py`) strips grounding issues from the raw feedback dict before it reaches the generator, so mixed partials (quality issues + grounding gap) only show actionable issues to the generator.

Planner prompts in [`docs/openclaw-agents/`](./openclaw-agents/) should reference `identity_context.facets_json.evolution_signals` and `recent_quality_trend` when choosing **success_criteria** and **evaluation_targets**.

## `replan_context` (planner replan input)

When `iteration_index > 0`, `planner_node` adds a `replan_context` to the planner payload:

| Field | Meaning |
|-------|---------|
| `replan` | Always `True` |
| `iteration_index` | Current iteration number |
| `prior_build_spec_id` | DB ID of the spec from the prior iteration |
| `prior_build_spec_digest` | SHA-256[:16] of the full prior spec — lets planner verify it's seeing the right plan |
| `prior_build_spec` | **Slim subset** of the prior build_spec (replan-relevant keys only; creative/crawl blobs stripped) |
| `prior_evaluation_report` | `{status, summary, issues}` only — no internal metrics |
| `retry_context` | Orchestrator-selected retry direction (`retry_direction`, `alignment_trend`, `failed_criteria_ids`) |

The slim `prior_build_spec` retains: `experience_mode`, `surface_type`, `canonical_vertical`, `site_archetype`, `success_criteria`, `evaluation_targets`, `literal_success_checks`, `cool_generation_lane`, `interaction_model`, `selected_urls`, `required_libraries`, `library_hints`, `machine_constraints`.

The crawl_context in the planner payload is also compacted on replans (visited count, phase, exhaustion only — full page summaries already incorporated in iteration 0's plan).

## `evolution_signals` (identity profile)

Written in [`identity/hydrate.py`](../services/orchestrator/src/kmbl_orchestrator/identity/hydrate.py) (`upsert_identity_evolution_signal`) after staging. Each signal includes `evaluation_status`, `evaluation_summary`, `issue_count`, optional `staging_snapshot_id`. Facets also carry `recent_quality_trend` derived from recent statuses.

Planners should **prefer** addressing recurring issues and **respect** improving vs stuck trends when proposing new directions.

## Identity context flags

| Flag | When |
|------|------|
| `is_fallback` | Synthetic default profile used (dev-friendly; disable with `KMBL_IDENTITY_ALLOW_FALLBACK_PROFILE=false`). |
| `identity_unresolved` | No profile/facets and fallback disallowed — planner must not assume a real scrape. |

## Payload compaction on iterations > 0

The orchestrator applies progressive compaction to reduce cross-boundary payload churn on retries:

| What | Where compacted | When |
|------|----------------|------|
| `build_spec` (generator) | Slimmed to `_BUILD_SPEC_ITERATION_KEYS`; full spec replaced, digest retained | Generator iteration > 0 |
| `prior_build_spec` (planner replan) | Slimmed to `_PLANNER_REPLAN_SPEC_KEYS`; digest added | Planner iteration > 0 |
| `crawl_context` (planner replan) | Compact: counts/phase/exhaustion only | Planner iteration > 0 |
| `structured_identity` (generator, evaluator) | Capped lists via `compact_structured_identity` | Iteration > 0 |
| `previous_evaluation_report` (evaluator) | `status/summary/issues[:5]/alignment_score` only via `compact_previous_evaluation_report_for_llm` | Evaluator iteration > 0 |
| `event_input` (generator) | `compact_generator_event_input` strips crawl page bodies | Generator iteration > 0 |

See `runtime/generator_iteration_compact_v1.py` for all compaction functions.
