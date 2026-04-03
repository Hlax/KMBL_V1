# Operator truth: loop, identity URL, and replanning

This document states **what the orchestrator actually does**, so product and operator expectations match the implementation.

## One planner per graph run (initial path)

Each `run_graph` / LangGraph invocation runs:

`context_hydrator` → `planner` → `generator` → `evaluator` → `decision_router` → …

## Generator-only iteration (default retry path)

When the evaluator outcome is `fail` or `partial` and iterations remain, `decision_router` usually routes to **`generator`** again with **`iteration_feedback`** (prior evaluation report), **`iteration_plan`**, and **`retry_context`**. The **`build_spec` produced by the first planner call in that run stays fixed** unless a replan route fires (below).

This is documented in [19_EVALUATOR_DECISION_POLICY.md](19_EVALUATOR_DECISION_POLICY.md).

## Replanning mid-run (pivot / fresh_start / stagnation)

When enabled via settings, an **iterate** decision can route to **`planner`** instead of **`generator`** so a **new `build_spec`** is persisted for the **same graph run** (orchestrator-owned). Triggers include:

- **`retry_direction`** in `pivot_layout`, `pivot_palette`, `pivot_content`, or `fresh_start`
- **`retry_direction`** `refine` with **working-staging stagnation** at or above **`graph_replan_stagnation_threshold`** (when that threshold is &gt; 0)

See `graph_replan_on_iterate_enabled` and `graph_replan_stagnation_threshold` in orchestrator settings / root `.env.example`.

The planner payload may include **`replan_context`** (prior evaluation, prior `build_spec` id, `retry_context`) when **`iteration_index` &gt; 0**.

## Identity URL: what persists vs what the planner may browse

- **Canonical URL → identity persistence in KMBL:** On `POST /orchestrator/runs/start`, the orchestrator runs **server-side extraction** (`extract_identity_from_url`: HTTP fetch + HTML parsing, optional multi-page crawl budget) and writes **`identity_source`** / **`identity_profile`** via `persist_identity_from_seed`. **`identity_brief`** and **`structured_identity`** are built in **`context_hydrator`** from those rows (not from planner prose).
- **Continuation:** If the client sends the same **`thread_id`**, **`identity_id`**, and **`identity_url`**, the orchestrator **skips re-extract** and uses the existing profile.
- **KiloClaw planner (Playwright / mcporter):** The planner role **may** use browser tooling for grounding when **`identity_url`** is present; that is **not** a second persistence pipeline in the orchestrator. Treat Playwright as **optional enrichment** for the agent, not as the source of truth for stored identity rows unless a separate product path writes crawl results back into **`identity_source`**.

## Telemetry

Graph run events include routing decisions. Look for **`decision_made`**, **`decision_iterate`**, and planner/generator invocation events to distinguish **replan** (second+ planner in one run) from **generator-only** iteration.
