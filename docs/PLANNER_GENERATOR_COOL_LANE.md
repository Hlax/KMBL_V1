# Planner → generator vertical: diagnosis, contract, and cool-generation lane

This document captures the **failure mode** (ambitious language vs shallow enforceable output), **concrete schema direction**, **minimal code already added** in-repo, and **what to postpone** until one strong end-to-end path works.

## 1. Diagnosis — where the contract is too weak

| Area | Issue |
|------|--------|
| **Wire contract** | `PlannerRoleOutput` treats `build_spec` as `dict[str, Any]` — no required separation between *taste* and *execution*. Anything goes; the generator can ignore rich fields. |
| **Persistence validation** | `_PlannerBuildSpecShape` only requires `type`, `title`, `steps`. That is correct for DB safety but does **not** encode ambition, libraries, or literal checks. |
| **Normalization** | `normalize_planner_output` persists `spec_json` as an opaque blob — **two-layer fields** (`creative_brief`, `execution_contract`, `literal_success_checks`) are preserved in JSON; `compact_planner_wire_output` now trims those lists/strings without dropping keys. |
| **Planner SOUL** | Already describes `variation_levers`, `experience_mode`, and anti-patterns, but **success_criteria / evaluation_targets** often collapse to weak “text present” checks unless the model is pushed hard. |
| **Generator SOUL** | Correctly says “execute build_spec” and avoid placeholders, but without **machine-checkable** obligations from the planner, the cheapest valid bundle still wins. |
| **Evaluator** | LLM judgment is easy to satisfy; **post-hoc** gates exist (`apply_preview_surface_gate`, 3D keyword guardrail) but there was **no** generic hook for **planner-authored literal substring checks** against artifact bodies. |
| **Payload** | `generator_node` still sends full `build_spec`, `event_input`, `identity_brief`, `structured_identity`, staging facts — repetition is a **latency/cost** issue, not fixed in the first slice. |

**Root cause:** Creative intent lives in prose-like fields; **enforceability** lives in separate lists (`success_criteria`, `evaluation_targets`) that are not mechanically tied to `experience_mode` or to artifact content. The evaluator can pass while artifacts miss what the plan claimed.

## 2. Code-level recommendations (surgical)

1. **Two-layer `build_spec` (convention + docs first)**  
   - **`creative_brief`**: mood, taste, identity interpretation — human/planner-readable, not used for machine gates.  
   - **`execution_contract`**: compact, enumerable fields the generator must satisfy or explicitly downgrade (see §3).  
   - **`literal_success_checks`**: list of substrings that **must** appear in concatenated static artifact content (implemented in orchestrator).

2. **Orchestrator literal gate (implemented)**  
   - After the LLM evaluator, run `apply_literal_success_checks` so a pass cannot ignore planner-mandated needles (e.g. real image URL, library name, data-attribute markers).

3. **No silent ambition drop**  
   - **Generator** must emit **`contract_failure`** when the plan is impossible, or top-level **`execution_acknowledgment`** (status + optional `ambition_downgrades`) — orchestrator tags silent omission via `_kmbl_compliance` (see `cool_generation_lane.py`).  
   - **Evaluator** already downgrades to `partial` when `experience_mode` implies 3D but artifacts lack 3D tokens — keep that; add literal checks for non-3D obligations.

4. **Reference patterns**  
   - Planner lists **`execution_contract.selected_reference_patterns`** (1–3 labels) and **`pattern_rules`** (short imperative bullets). Generator receives them inside `build_spec`; no change to payload shape required beyond nested keys.

5. **Payload efficiency (later)**  
   - Pass **hashes / summaries** for identity blobs; single persisted row IDs — **postpone** until the literal lane proves value.

## 3. Proposed schema (planner output / `build_spec`)

Top-level planner JSON keys stay: `build_spec`, `constraints`, `success_criteria`, `evaluation_targets`.

Inside **`build_spec`** (additive):

```json
{
  "type": "...",
  "title": "...",
  "steps": [],

  "creative_brief": {
    "mood": "warm editorial",
    "direction_summary": "1–3 sentences",
    "identity_interpretation": "how we read the URL identity"
  },

  "execution_contract": {
    "surface_type": "single_page_static | multi_file_static | ...",
    "layout_mode": "stacked_sections | editorial_split | ...",
    "required_sections": ["hero", "work", "contact"],
    "required_assets": [{ "role": "hero_image", "source": "identity", "min_count": 1 }],
    "required_interactions": [{ "id": "scroll_reveal", "mechanism": "css_or_js" }],
    "required_visual_motifs": ["oversized_type", "restrained_motion"],
    "allowed_libraries": ["gsap", "three"],
    "forbidden_fallback_patterns": ["generic_hero_centered_only"],
    "selected_reference_patterns": ["portrait_led_editorial_hero"],
    "pattern_rules": [
      "Hero uses one identity image at large scale, not thumbnail grid",
      "At least one heading uses display scale (>48px equivalent)"
    ],
    "downgrade_rules": [
      { "if": "webgl_unavailable", "then": "css_parallax_or_static_hero_with_depth", "must_document": true }
    ],
    "lane": "cool_generation_v1"
  },

  "literal_success_checks": [
    "https://example.com/real-asset-path.jpg",
    "data-kmbl-motion=\"1\""
  ]
}
```

**Notes:**

- **`literal_success_checks`** is the fastest path to **literal** enforcement without waiting for evaluator upgrades.  
- **`lane`** is optional metadata for tooling; literal checks apply whenever `literal_success_checks` is non-empty.

## 4. Generator input / output tweaks

**Input:** Full `build_spec` plus orchestrator fields **`cool_generation_lane_active`** and **`kmbl_execution_contract`** (compact summary — lane, patterns, pattern_rules count, literal check count).

**Output (optional, additive) — top-level `execution_acknowledgment`:**

```json
{
  "execution_acknowledgment": {
    "status": "executed",
    "ambition_downgrades": [
      { "from": "webgl_3d_portfolio", "to": "flat_hero_with_gsap_parallax", "reason": "single-file budget" }
    ],
    "rules_attempted": ["pattern_rules:hero_image"],
    "rules_skipped": []
  }
}
```

**Status vocabulary:** `executed` | `downgraded` | `cannot_fulfill`. If cool lane is active and artifacts are emitted without a **non-empty `status`**, the orchestrator sets **`_kmbl_compliance.silent_acknowledgment`** and the evaluator downgrades to **partial**.

## 5. Validation changes for the cool-generation lane

| Check | Mechanism |
|-------|-----------|
| Artifacts present | Existing generator persistence + staging |
| Preview healthy | `apply_preview_surface_gate` |
| 3D vs `experience_mode` | Existing keyword guardrail in `evaluator_node` |
| **Planner literal needles** | **`apply_literal_success_checks`** |
| **Pattern labels → tokens** | **`kmbl-pattern-…`** strings merged into **`literal_success_checks`** |
| **Motion / non-static fallback** | **`apply_cool_lane_motion_signal_gate`** (CSS `@keyframes` / `animation:` / `transition:` or non-trivial `<script>`); skipped when **`status`** is **`cannot_fulfill`** |
| Placeholder-only JS | **Postpone** — deeper than current script-length heuristic |
| Acknowledgment | **`apply_cool_lane_execution_acknowledgment_gates`** — silent or invalid **`status`** → **partial** |

## 6. Smallest end-to-end plan

1. Set **`event_input.cool_generation_lane`: `true`** *or* **`build_spec.execution_contract.lane`: `"cool_generation_v1"`** so **`apply_cool_generation_lane_presets`** merges defaults (patterns, rules, literal needles including first `identity_brief.image_refs` URL when present).  
2. **Generator** embeds needles in static files and sets **`execution_acknowledgment.status`** to `executed` or `downgraded` (or **`contract_failure`**).  
3. **Orchestrator** runs **`apply_literal_success_checks`**, **`apply_cool_lane_motion_signal_gate`**, then **`apply_cool_lane_execution_acknowledgment_gates`** after the LLM evaluator.  
4. Tune prompts if the model still ships generic bundles.

## 7. Postpone until the path works

- Subjective evaluator rubrics and alignment scoring tuning.  
- Full payload deduplication / content-addressed blobs.  
- Strict JSON Schema validation for `execution_contract` in pydantic (add once stable).  
- AST-based “non-placeholder JS” detection.  
- Automatic synthesis of `literal_success_checks` from identity (could hallucinate needles — keep human/planner in the loop first).

## 8. Implementation status (this repo)

- **Cool lane:** `runtime/cool_generation_lane.py` — presets, **`literal_success_checks_preview`** in **`kmbl_execution_contract`**, **`reference_pattern_to_literal_token`** / pattern needles, **`EXECUTION_ACKNOWLEDGMENT_STATUSES`**, acknowledgment annotation + **`apply_cool_lane_execution_acknowledgment_gates`**.  
- **Literal + motion:** `runtime/literal_success_gate.py` — `apply_literal_success_checks`, **`apply_cool_lane_motion_signal_gate`**.  
- **Planner compact:** `contracts/planner_normalize.py` — preserves/trims `creative_brief`, `execution_contract`, `literal_success_checks`.  
- **Generator input contract:** `contracts/role_inputs.py` — `cool_generation_lane_active`, `kmbl_execution_contract` (includes preview list).  
- **Generator wire output:** `contracts/role_outputs.py` — optional `execution_acknowledgment`.  
- **Docs:** `docs/openclaw-agents/kmbl-planner/SOUL.md`, `docs/openclaw-agents/kmbl-generator/SOUL.md`, **`kmbl-generator/USER.md`**, `docs/openclaw/README.md` (runtime sync).  
- **Tests:** `tests/test_literal_success_gate.py`, `tests/test_cool_generation_lane.py`.
