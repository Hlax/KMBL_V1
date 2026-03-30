# Gallery smoke stability (pre–image-provider)

KMBL is the execution authority; KiloClaw is only the role layer. Before adding **OpenAI image generation** (or other second-provider paths), the **base gallery loop** should be dependable enough that new failures are easy to attribute.

This document defines a **stability bar** for the existing gallery presets only:

- `seeded_gallery_strip_v1` (deterministic)
- `seeded_gallery_strip_varied_v1` (varied)

## Deterministic gallery (`seeded_gallery_strip_v1`)

A deterministic gallery smoke run should:

- Start successfully (`POST /orchestrator/runs/start` → 200).
- Complete successfully (`graph_run.status` → `completed`).
- Persist planner / generator / evaluator outputs (role invocations completed in run detail).
- Create a **staging snapshot** (visible in run detail / snapshot).
- Return run detail without persistent **500**s on `GET /orchestrator/runs/{id}` or `/detail`.
- Preserve a **stable gallery structure** in staging (`ui_gallery_strip_v1` with items).
- Avoid **duplicate checkpoint** failures after ambiguous Supabase retries (checkpoint upsert idempotency).
- **Survive transient retryable Supabase disconnects** when they occur (`RemoteProtocolError` retried; run still completes).

## Varied gallery (`seeded_gallery_strip_varied_v1`)

Everything in the deterministic list, plus:

- **Variation inputs** visible in `effective_event_input` / snapshot (`run_nonce`, bounded variants).
- **Planner parsing** tolerates real model output (e.g. prose-prefixed JSON normalized by KMBL).
- **Checkpoint persistence** stable under transport retry (same as deterministic).
- **Gallery artifact linkage** coherent in staging: items present; artifact keys or placeholder URLs acceptable until a real image provider exists.

## Shared expectations

- **No raw provider formatting** becomes product truth — KMBL normalizes and persists structured rows; staging is review surface, not canon by itself.
- **Checkpoint / retry** flow is stable (transport retries + checkpoint idempotency where implemented).
- **KiloClaw structured outputs** remain validated and normalized by KMBL contracts before persistence.
- **Failures**, when they occur, should be attributable to a **single clear layer** (see failure categories in `scripts/smoke_stability.py`).

## Automation

Run with validation output:

```bash
cd services/orchestrator
python scripts/run_graph_smoke.py --preset seeded_gallery_strip_v1 --validate-stability
python scripts/run_graph_smoke.py --preset seeded_gallery_strip_varied_v1 --validate-stability
```

Or both:

```bash
python scripts/validate_gallery_smoke.py
```

End of report: `stability_check: pass | partial | fail` and a primary **failure category** when not pass.

## “Stable enough” for image provider work

Proceed when both presets reach **`stability_check: pass`** (or **`partial`** only for known, documented gaps such as placeholder image URLs) under your real KiloClaw + Supabase environment, and failures classify cleanly — not when adding new providers would mix multiple unknowns.
