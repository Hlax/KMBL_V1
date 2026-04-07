# Evaluator decision policy (iterate vs stage)

## Implementation

Routing after the evaluator is implemented in `compute_evaluator_decision` in
[`services/orchestrator/src/kmbl_orchestrator/graph/helpers.py`](../services/orchestrator/src/kmbl_orchestrator/graph/helpers.py),
followed by post-compute overrides in `decision_router` for special cases.

**Inputs used for the branch:**

| Input | Role |
|-------|------|
| `evaluation_report.status` | `pass` → stage; `blocked` → interrupt; `fail` / `partial` → iterate or stage |
| `iteration_index` | Compared to `max_iterations` |
| `max_iterations` | From graph state / settings |

**Not used for branching:** `alignment_score`, `alignment_signals`, or `alignment_score_history`.

Those fields are computed and persisted for **steering the generator** on the next iteration (`retry_context`, `iteration_plan`, working staging, identity evolution), not for deciding **whether** to iterate.

## Grounding-only partial override

When demo/public mode (`KMBL_ORCHESTRATOR_PUBLIC_BASE_URL` is set) requires a browser-reachable preview but one cannot be satisfied, the evaluator gate downgrades `pass → partial` and sets `metrics.grounding_only_partial = True`.

`decision_router` detects this flag **after** `compute_evaluator_decision` and overrides `iterate → stage` (degraded):

- Build quality was acceptable — generator iteration would be wasteful since the generator cannot fix a preview infrastructure gap.
- A `DEGRADED_STAGING` event is emitted with `grounding_only_partial = True` and `preview_grounding_fallback_reason` for operator visibility.
- The operator can fix this by providing a publicly-reachable tunnel URL (`KMBL_ORCHESTRATOR_PUBLIC_BASE_URL`).

**Key: a `partial` status that was produced only by the grounding gate will never trigger a generator retry.**

See `runtime/demo_preview_grounding.py` (`is_grounding_only_partial`) and `graph/nodes_pkg/decision.py`.

### Grounding-only vs quality-partial distinction

| Case | `grounding_only_partial` | `decision` | Why |
|------|--------------------------|------------|-----|
| Build pass, no browser preview in demo mode | `True` | `stage` (degraded) | Generator can't fix infra |
| Build has real quality issues | `False` | `iterate` (under max) | Generator should refine |
| Build has quality issues + grounding gap | `False` | `iterate` (under max) | Quality issues take priority |

## Product implications

- **Low alignment does not** by itself stop iteration or force staging — unless the evaluator emits a status that maps to `pass` / `stage` under the rules above, or you hit `max_iterations`.
- If product requirements call for “stop iterating when alignment is high enough” or “never stage below threshold X,” that would be a **policy change** in `compute_evaluator_decision` (or a separate gate before staging), with tests.
- **Demo mode grounding** is enforced as a non-retryable degraded stage — it is never silently ignored.

## Iterate path: generator vs planner

When the decision is **iterate**, the default route is `decision_router` → **generator** with orchestrator-provided `retry_context` and prior **`build_spec`** unchanged.

When **replan routing** is enabled (`graph_replan_on_iterate_enabled`), the graph may route `decision_router` → **planner** instead (same graph run, new `build_spec` row) if `should_route_to_planner_on_iterate` returns true — e.g. **`retry_direction`** is `pivot_*` / `fresh_start`, or stagnation exceeds **`graph_replan_stagnation_threshold`** while direction is `refine`. See [`OPERATOR_LOOP_AND_IDENTITY.md`](OPERATOR_LOOP_AND_IDENTITY.md).

## Reference

- Operator truth (identity URL, iteration): [OPERATOR_LOOP_AND_IDENTITY.md](OPERATOR_LOOP_AND_IDENTITY.md)
- Runtime overview: [04_RUNTIME_LOOP.md](04_RUNTIME_LOOP.md)
- API: [12_API_AND_SERVICE_LAYER.md](12_API_AND_SERVICE_LAYER.md)
- Demo preview grounding contract: `services/orchestrator/src/kmbl_orchestrator/runtime/demo_preview_grounding.py`
