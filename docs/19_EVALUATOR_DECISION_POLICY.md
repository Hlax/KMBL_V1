# Evaluator decision policy (iterate vs stage)

## Implementation

Routing after the evaluator is implemented in `compute_evaluator_decision` in
[`services/orchestrator/src/kmbl_orchestrator/graph/app.py`](../services/orchestrator/src/kmbl_orchestrator/graph/app.py).

**Inputs used for the branch:**

| Input | Role |
|-------|------|
| `evaluation_report.status` | `pass` → stage; `blocked` → interrupt; `fail` / `partial` → iterate or stage |
| `iteration_index` | Compared to `max_iterations` |
| `max_iterations` | From graph state / settings |

**Not used for branching:** `alignment_score`, `alignment_signals`, or `alignment_score_history`.

Those fields are computed and persisted for **steering the generator** on the next iteration (`retry_context`, `iteration_plan`, working staging, identity evolution), not for deciding **whether** to iterate.

## Product implications

- **Low alignment does not** by itself stop iteration or force staging — unless the evaluator emits a status that maps to `pass` / `stage` under the rules above, or you hit `max_iterations`.
- If product requirements call for “stop iterating when alignment is high enough” or “never stage below threshold X,” that would be a **policy change** in `compute_evaluator_decision` (or a separate gate before staging), with tests.

## Iterate path skips planner

When the decision is **iterate**, the graph routes `decision_router` → **generator** (not back through planner). The planner already ran once for this graph invocation; retries are generator/evaluator loops with orchestrator-provided `retry_context`.

## Reference

- Runtime overview: [04_RUNTIME_LOOP.md](04_RUNTIME_LOOP.md)
- API: [12_API_AND_SERVICE_LAYER.md](12_API_AND_SERVICE_LAYER.md)
