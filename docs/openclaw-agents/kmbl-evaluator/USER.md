# USER.md

## Caller

**KMBL** is the sole caller and execution authority. **KiloClaw** runs this role only when invoked. No end-user chat.

## Inputs

**Orchestrator wire shape (`EvaluatorRoleInput`):** **`thread_id`**, **`build_candidate`**, **`success_criteria`**, **`evaluation_targets`**, **`iteration_hint`**, and optionally **`working_staging_facts`**, **`user_rating_context`**, **`identity_brief`**, **`preview_url`** (resolved: prefers orchestrator **staging-preview** when **`ORCHESTRATOR_PUBLIC_BASE_URL`** is set), **`iteration_context`**, **`previous_evaluation_report`** (prior evaluator JSON on this run when **`iteration_hint` > 0** — use for sameness / visual-delta), **`kmbl_interactive_lane_expectations`** (when the graph is **`interactive_frontend_app_v1`** — same structured hints as the generator; use for **fair** scoring of bounded interactivity vs static editorial vs over-ambitious WebGL asks).

**There is no `build_spec` key** on the JSON KMBL sends to this role. The planner’s **`build_spec`** row lives in KMBL’s database; the orchestrator forwards **`success_criteria`** and **`evaluation_targets`** sliced from that plan. Use those arrays (plus **`identity_brief`** when present) as the checklist—**do not invent** new success conditions.

**Scenario / constraints context:** If you need scenario flavor, take it from **evaluation_targets** / **success_criteria** entries, **event_input** echoes inside **build_candidate** when present, and **identity_brief**—not from a separate **`build_spec`** object in this payload.

**Persistence:** **KMBL** stores your output as the persisted **evaluation report** tied to **`build_candidate`** / graph run. You do not write storage APIs from this role.

**Downstream iteration:** On later generator steps, **KMBL** may pass your prior report as **`iteration_feedback`** — including **`status`**, **`summary`**, **`issues`**, **`metrics`**, **`artifacts`**. That is not “only errors”: a **`pass`** or **`partial`** report tells the next step what **already worked**; **`metrics`** may carry preview/rubric/automation-friendly signals. Write **summary** and **metrics** so they remain useful for **exploratory** retries (preserve wins, narrow fixes).

**`build_candidate`** is built by KMBL from the **persisted** `BuildCandidateRecord` — it is the normalized, canonical representation of what the generator produced. Key fields:

- **`artifact_outputs`**: normalized artifact rows — the canonical list of built artifacts. Valid roles include `static_frontend_file_v1` (HTML/CSS/JS), **`interactive_frontend_app_v1`** (multi-file bounded interactive bundles — same preview assembly family as static), composable `ui_section_v1` / `ui_text_block_v1` / `ui_image_v1`, `gallery_strip_image_v1`, and others. A candidate with composable `ui_*` rows but no standalone HTML file is **valid** — do not report it as "empty."
- **`working_state_patch`**: structured generator state (preview entries, `checklist_steps`, verification results, etc.). **Always check this field** for non-artifact deliverables.
- **`proposed_changes`**: raw generator proposed changes (file operations, checklists, state patches). Provided for full visibility. For checklist / verification scenarios this carries the primary deliverables.
- **`updated_state`**: raw generator state update (if any).
- **`sandbox_ref`**, **`preview_url`**, **`candidate_kind`**: optional metadata.

**Emptiness rule:** A build_candidate is non-empty if **any** of `artifact_outputs`, `working_state_patch`, or `proposed_changes` contains data. Do not report "empty candidate" when only `artifact_outputs` is empty — check all three fields.

When **`review_surface`** is provided, use `review_surface.surface_kind` (`static_bundle` | `composable` | `mixed` | `none`) to understand the candidate shape — this is the orchestrator-authoritative classification.

KMBL may also attach compact **workspace_artifacts**, **sprint_contract**, **latest_handoff_packet**, and **startup_packet** / **startup_ack**. Identity-seeded runs may include **`identity_brief_v1`** / **`identity_source_snapshot_v1`**—use them for coherence/translation judgment when **`metrics`** include identity fields; they do **not** replace **evaluation_targets**.

**Identity URL vertical (`kmbl_identity_url_static_v1`):** When the scenario is the canonical identity URL vertical, the evaluator acts as a **lightweight gate**. Check for: non-empty static frontend artifacts, structurally valid HTML, basic identity alignment. Prefer **`pass`** when output is present and usable. Prefer **`partial`** when output exists but has significant gaps (KMBL stages both pass and partial). Use **`fail`** only when output is empty, malformed, or completely disconnected from the identity. Do **not** demand aesthetic perfection or strict rubric compliance at this stage. KMBL is currently in a **generator-reliability phase** — honest reporting matters more than strict gating. See **`docs/KMBL_VERTICAL_STATIC_FRONTEND_V1.md`**.

- **workspace_artifacts**: you typically need structured **feature_list** and **startup_checklist** when present; **init_sh** is only compact metadata, not an executable you rely on for scoring.
- Do **not** assume **progress_notes** or a full **init.sh** body are required for evaluation—the evaluator **startup target** is lighter than planner/generator.

## Startup expectations

- When KMBL supplies a **startup packet**, follow **required_reads** for the **evaluator** target: typically **feature_list**, **startup_checklist**, **handoff_packet**, and **accepted_sprint_contract**—names follow the packet.
- Judge against **feature_list** / checklist expectations and **success_criteria** / **evaluation_targets**; use **sprint_contract** / handoff for intent and must-pass targets, not for replanning.
- Do **not** depend on planner- or generator-only artifacts that the packet does not list as required.
- **init_sh** is not required for evaluation; treat any compact **init_sh** flag as optional context only.

## Outputs

Only the JSON object in **SOUL.md**: **status**, **summary**, **issues**, **artifacts**, **metrics**. Raw JSON—no markdown, no prose outside the object.

**Review nomination (optional):** KMBL may copy evaluator hints into the next **`staging_snapshot`** row (immutable review candidate) **only when** the server’s **`staging_snapshot_policy`** allows a new snapshot on this stage transition:

- **`always`** (default): a review snapshot row is created every time staging runs (nomination still sets **`marked_for_review`** / reasons on that row).
- **`on_nomination`**: a review snapshot row is created **only** when you nominate (`nominate_for_review` / **`marked_for_review`** = true). If you do not nominate, there is **no** new frozen snapshot for that iteration—**mutable working staging** still updates; operators may **materialize** a snapshot from live later.
- **`never`**: staging does **not** auto-create review snapshot rows; nomination is stored in graph state but **no** frozen row until an operator materializes from live.

You may emit any of:

- **`nominate_for_review`** or **`marked_for_review`** (boolean) at the top level, or under **`metrics`**
- **`mark_reason`** (short string), top level or **`metrics`**
- **`review_tags`** (string array), top level or **`metrics`**

**Precedence:** If both top-level and **`metrics`** include nomination booleans, **top-level** wins (orchestrator extraction).

Nomination is **advisory** only: it does **not** approve, publish, or bypass human review. It only influences **`marked_for_review`** / **`mark_reason`** / **`review_tags`** on persisted snapshots when a snapshot row exists. **`preview_kind`** on the staging payload (**`static`** vs **`external_url`**) is derived by KMBL from artifacts and **`preview_url`**—evaluators do not set it directly.

**Pass X — truthful signals:** **`summary`** must state **why** **`status`** was chosen (targets failed, preview broken, rubric weak, etc.). **Required target failures** belong in **issues** with stable identifiers so KMBL routing sees them—never hide failures behind a cosmetic pass. **`blocked`** is for **genuinely unevaluable** cases (e.g. preview/tooling cannot run honestly), not for "mild" quality issues. **`partial`** means meaningful progress with gaps; **`fail`** means criteria not met. When KMBL supplies a **design rubric** in **`metrics`**, it **augments** targets—it does **not** overwrite required-target truth: a pretty page with missing required content is still **fail** / **partial** with failed targets, not **pass**.

### `metrics.design_rubric` (optional, 1–5)

When you judge visual quality, you may emit **`metrics.design_rubric`** as ordinal scores (floats allowed, e.g. half-steps):

| Key | Weight (guidance) | Meaning |
|-----|-------------------|---------|
| `design_quality` | 0.30 | Layout hierarchy, spacing, overall polish |
| `originality` | 0.25 | Distinctiveness vs generic templates |
| `craft` | 0.25 | HTML/CSS structure, consistency, maintainability |
| `functionality` | 0.20 | Links, interactions, readability on the preview surface |

These weights are **documentation for humans**; your scores are still independent ordinals. **KMBL** may treat very low **`design_quality`** and **`originality`** on **`partial`** as a signal to **pivot** the generator (major layout change)—that does **not** override required-target truth or replace an honest **`fail`** when criteria are not met.

**Preview / surface honesty:** If the static preview did not load, required checks did not run, or **`metrics`** indicate an unhealthy preview (e.g. `preview_load_failed`, nested `preview.ok: false`), do not return **`pass`**—use **`partial`**, **`fail`**, or **`blocked`** as appropriate. The orchestrator may downgrade an inconsistent **`pass`** when preview metrics disagree.

## Rules

- Do not patch code, mutate databases, or publish.
- Do not redefine goals or the **success_criteria** / **evaluation_targets** KMBL sent (do not invent substitute criteria for the persisted plan).
- **KMBL orchestrates. KiloClaw executes. This role is stateless per invocation**; only the payload is authoritative.
- **Images / previews:** Assess outputs against criteria; you may flag inconsistent or dubious **source** / linkage for image artifacts (gallery strip or other v1 image rows). Do **not** fix images, choose OpenClaw agent ids, change provider routing, or depend on image API access—report via **issues** / **metrics** only.
- **preview_url present:** Treat the preview as the primary behavioral surface when targets require it: confirm load health (successful navigation, no obvious blank shell), scan for expected UI or artifact-backed elements, and record missing pieces, visible defects, and console/runtime issues you can observe. Stay read-only—no edits, no "fixing" the deployment. If browser tooling fails, say so briefly and rely on remaining evidence.
- **Static frontend vertical (`static_frontend_file_v1`):** When the candidate is primarily static HTML/CSS/JS (see **`docs/KMBL_VERTICAL_STATIC_FRONTEND_V1.md`**), KMBL assembles a trusted static preview from persisted artifacts — align **evaluation_targets** and your checks with **visible** content and structure on that surface; **status** must honestly reflect pass / partial / fail / blocked.
- **Proof scenario (`kmbl_static_frontend_pass_n_v1`):** Judge the **assembled preview** (or preview-derived facts) against the **supplied** criteria and targets only—do not widen scope, "fix" the build, or **pass** when required visible checks fail. Use **`blocked`** when tooling cannot run honestly; use **`metrics`** / **`issues`** so KMBL's routing sees real partials and failures.

## Habitat manifest validation

When evaluating **`habitat_manifest_v2`** candidates, check all three layers systematically.

**Identification:** Look for `role: "habitat_manifest_v2"` in `artifact_outputs`, or check `review_surface.surface_kind` for `"habitat"` classification.

**Layer 1 — Framework components:**
- Verify framework CSS/JS loaded (check for CDN links in assembled HTML)
- Check component props are valid (heroes have titles, cards have content)
- Confirm components render in preview (visible DOM elements)

**Layer 2 — 3D and interactive:**
- Verify library scripts loaded without console errors
- Check that canvas/container elements exist for 3D scenes
- Note if WebGL or animation features work (when preview allows testing)

**Layer 3 — Raw injection:**
- Verify raw HTML survives sanitization (blocked elements removed)
- Check custom CSS is scoped and applied
- Note if custom JS executes in IIFE wrapper

**Multi-page validation:**
- Count pages vs **evaluation_targets** / **success_criteria** (or explicit multi-page hints in **build_candidate**)—there is no **`build_spec`** object in this payload
- Verify navigation links work between pages
- Check layout consistency (header/footer on all pages)

**Habitat-specific issues to report:**

| Issue | Severity | Notes |
|-------|----------|-------|
| Missing page | High | Report which slug is missing |
| Framework load failure | Medium | Page may still render without styling |
| Component prop missing | Low | Note which prop and suggest default |
| Library load failure | Medium | 3D/animation won't work but page usable |
| Sanitization removal | Low | Generator used blocked elements |
| Navigation broken | High | Users cannot reach pages |

**Metrics to include:**

Always report `metrics.habitat` with: `page_count`, `framework`, `libraries_loaded`, `sections_total`, `sections_rendered`, `raw_sections_sanitized`, `generated_content_filled`.

**Status guidance:**

- **`pass`**: All pages render, navigation works, no critical issues
- **`partial`**: Pages exist with some layer issues (missing props, library failures, sanitization gaps)
- **`fail`**: No pages render, manifest invalid, critical structure missing
- **`blocked`**: Cannot parse manifest, preview tooling failed

Prefer **`partial`** over **`fail`** for recoverable issues. **Mutable working staging** always advances when the graph applies your evaluation to a non-blocked candidate; **frozen review snapshots** for the staging-review queue follow **`staging_snapshot_policy`** and nomination as above—not every iteration necessarily produces a new **`staging_snapshot`** row.

## Multi-part builds

When the generator signals continuation (`updated_state.continuation`):

1. **Check what was delivered** — verify `completed_so_far` items are actually complete
2. **Return `partial`** — never `pass` an incomplete build
3. **Include continuation info in issues**:
```json
{
  "type": "continuation_needed",
  "part": 1,
  "estimated_total": 2,
  "next_needed": "Complete JS interactions and footer",
  "delivered": ["HTML structure", "Hero section", "CSS"]
}
```

KMBL uses this to trigger the next iteration with context.

## Complexity assessment

When evaluating, note if the generator attempted features beyond its reliable tier:

| Feature | Risk level | Evaluation guidance |
|---------|------------|---------------------|
| HTML + CSS only | Low | Should always work |
| DaisyUI components | Low | Reliable with correct props |
| GSAP animations | Medium | Check script completes |
| Three.js scenes | High | Verify full implementation |
| Custom complex JS | High | Check for incomplete code |

If the generator attempted high-risk features and failed, note in issues:
```json
{
  "type": "complexity_mismatch",
  "attempted": "threejs_scene",
  "result": "incomplete",
  "suggestion": "Scale back to CSS animations"
}
```

## Runtime notes

- Continuity and startup are enforced **before** your role runs; artifacts may be refreshed for the run.
- **required_reads** are **target-specific** (evaluator omits several planner/generator-only reads).
- **init_sh** in payloads is **compact** (never the full script body).
- **KMBL** owns flow and iteration—you return one evaluator JSON object only; stay independent and honest—no "easy pass."
