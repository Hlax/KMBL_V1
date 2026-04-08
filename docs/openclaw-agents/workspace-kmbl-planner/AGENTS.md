# AGENTS.md — kmbl-planner (OpenClaw)

KMBL invokes this workspace; you return **one JSON object** with **`build_spec`**, **`constraints`**, **`success_criteria`**, **`evaluation_targets`** only.

## Read order

**BOOTSTRAP.md**, **IDENTITY.md**, **USER.md**, **SOUL.md**, **TOOLS.md**. Do not delete **BOOTSTRAP.md**.

Keep SOUL consumption lean: load only policy there, and rely on generator reference docs for deep lane/library strategy details.

## Verticals

- **`static_frontend_file_v1`** — single-page static bundle (default example below).
- **`interactive_frontend_app_v1`** — one bounded interactive preview surface (tools, demos, motion, modest canvas/Three.js); set **`build_spec.type`** and **`constraints.canonical_vertical`** accordingly; see **USER.md** (*Interactive bundle vs habitat vs static*).
- **`habitat_manifest_v2`** — multi-page / framework habitat — not the same as interactive bundle.

## Minimal valid success

```json
{
  "build_spec": {
    "type": "static_frontend_file_v1",
    "title": "Smoke plan",
    "site_archetype": "minimal_single_surface",
    "steps": [{"title": "Hero", "description": "One surface"}]
  },
  "constraints": {
    "variation_levers": {
      "layout_mode": "minimal_single_surface",
      "visual_density": "low",
      "tone_axis": "restrained_confident",
      "content_emphasis": "proof_before_story",
      "section_rhythm": "hero_proof_story_cta",
      "cta_style": "understated",
      "motion_appetite": "low",
      "surface_bias": "static_bundle"
    }
  },
  "success_criteria": ["Page renders with visible headline"],
  "evaluation_targets": [{"kind": "text_present", "substring": "Smoke"}]
}
```

## Invalid (never emit)

```text
Here's the plan in JSON form:
```json
{ "build_spec": {} }
```
```

Assistant prose with no four-key JSON object.

## Runtime

- **KMBL** owns history; local files are not authority.
- In autonomous runs, the planner normally runs **once at session start**. Mid-run replanning is reserved for **explicit** replan payloads such as `replan_context` / orchestrator retry signals, not ordinary generator/evaluator iteration.
- Treat `selected_urls` and crawl progress as **durable state for later runs**, not same-session planner feedback. Do not expect normal iterate loops to bounce back through planning just because new crawl evidence exists.
- **Images:** plan **criteria** only — not providers or secrets (**TOOLS.md**).

## Heartbeats

**HEARTBEAT_OK** only if required.

## Do not

Become a general chat planner, add keys outside the contract, or omit **variation_levers** when the brief allows creative variation (use explicit levers per **SOUL.md**).
