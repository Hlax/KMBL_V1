# Runtime paths: Autonomous UI, `/runs/start`, and crawl closure

This document explains how **two ways of running repeated graphs** relate to **crawl frontier advancement** (including optional **Playwright** via the local wrapper).

## Unified behavior (orchestrator)

After every **successful** LangGraph completion from **`POST /orchestrator/runs/start`** (control plane: `POST /api/runs/start`), the orchestrator calls **`advance_crawl_frontier_after_graph`** with the final graph state, **`identity_id`**, and **`thread_id`**. This matches the crawl closure that already ran after each graph in the **server autonomous loop tick** (`tick_loop` → `_tick_graph_run` → `_advance_crawl_frontier`).

So **Autonomous page “Start loop”** (client `while` + repeated starts) and **loop API ticks** both advance **durable crawl state** when an identity is present.

Implementation:

- `kmbl_orchestrator.application.run_lifecycle.run_graph_background` — after `run_graph` succeeds.
- `kmbl_orchestrator.autonomous.loop_service.advance_crawl_frontier_after_graph` — shared implementation.
- `kmbl_orchestrator.autonomous.loop_service._advance_crawl_frontier` — thin wrapper used only by the loop tick (passes `AutonomousLoopRecord` into the shared API).

## Autonomous control-plane “Start loop”

- **What it does:** The Next.js **Autonomous** page issues **`POST /api/runs/start`** in a loop (with optional interrupt), polling until each graph run reaches a terminal status, then waits and starts the next run.
- **Identity/thread:** Typically sends **`identity_id`** and **`thread_id`** from localStorage so the same identity and habitat thread are reused.
- **Crawl:** Uses the unified path above — each completed run advances the frontier (subject to crawl state existing for that identity and `identity_url` in `event_input`).

## Server autonomous loop (`/orchestrator/.../loops` API)

- **What it does:** `tick_loop` drives phases (`identity_fetch` → `graph_cycle` → …). Each **`graph_cycle`** invokes `run_graph_for_loop`, then **`_advance_crawl_frontier`** (wrapper) with the loop’s `identity_id` and `current_thread_id`.
- **Extras:** The loop also manages **exploration directions**, **retry_context**, and **auto-publish** thresholds — features not implied by the bare client loop.

## Playwright wrapper

- **Who calls it:** Not the planner LLM directly. The orchestrator may call **`visit_page_via_wrapper`** inside **`advance_crawl_frontier_after_graph`** when planner **`selected_urls`** match the offered frontier batch, the wrapper URL is set, and **`kmbl_playwright_max_pages_per_loop` > 0**.
- **Config:** `KMBL_PLAYWRIGHT_WRAPPER_URL`, `KMBL_PLAYWRIGHT_MAX_PAGES_PER_LOOP`, `KMBL_PLAYWRIGHT_INSPIRATION_DOMAINS` (see orchestrator settings).

## When crawl does not advance

- No **`identity_id`** on the run (crawl state is keyed by identity).
- **Smoke / planner-only** mode (`ORCHESTRATOR_SMOKE_PLANNER_ONLY`) — graph exits without full pipeline.
- **Graph run throws** before normal completion — the `else` path in `run_graph_background` is skipped.

See also: [CURRENT_PRODUCT_MODEL.md](CURRENT_PRODUCT_MODEL.md), [05_STATE_AND_SNAPSHOTS.md](05_STATE_AND_SNAPSHOTS.md).
