# CLAUDE.md

## Project context

This repo is part of the KMBL system.

Important local paths:

- **KMBL workspace root:** `C:\Users\guestt\OneDrive\Desktop\KMBL\KMBL_WORKSPACE`
- **Real OpenClaw install / live runtime repo:** `C:\Users\guestt\.openclaw`
- **This repo's OpenClaw agent mirror/reference folder:** `docs\openclaw-agents`

Treat these paths differently:

- `docs\openclaw-agents` contains the **reference / mirrored agent files and latest markdown guidance** used to reason about planner/generator/evaluator behavior inside this repo.
- `C:\Users\guestt\.openclaw` is the **real live OpenClaw environment** and may be the place where the currently running gateway, agent skills, canvas, and runtime behavior actually come from.
- `C:\Users\guestt\OneDrive\Desktop\KMBL\KMBL_WORKSPACE` is the **authoritative local workspace root for generated run artifacts**, including sandbox/materialized preview files.

Do not assume these locations are always perfectly synchronized. If debugging behavior mismatch, compare the mirror files in this repo against the live files under `.openclaw`.

---

## Working assumptions

- OS: Windows
- Shell: PowerShell unless otherwise specified
- The user commonly runs the orchestrator locally.
- Tailscale is available, but **local preview/debugging should be preferred first**.
- Networked preview through Tailscale is only a fallback if local preview access is unavailable or clearly broken.

---

## Preview and evaluator priority rules

### Always prefer local preview first

When investigating generator/evaluator/preview issues, use this order of operations:

1. **Local orchestrator preview endpoints**
   - Prefer the orchestrator's local working-staging and preview endpoints first.
   - If a thread ID or graph run ID is available, first check whether the preview is already materialized locally through orchestrator routes.

2. **Local workspace artifact path**
   - If the run includes `sandbox_ref` and/or `workspace_manifest_v1`, treat the local workspace output as the next authoritative source.
   - Look for files like:
     - `component\preview\index.html`
     - `component\preview\styles.css`
     - `component\preview\app.js`
   - Resolve them relative to the sandbox or workspace root before falling back to remote/browser assumptions.

3. **Direct local browser-compatible inspection**
   - If the evaluator/browser cannot reach a preview URL, prefer a local file/materialized preview strategy rather than immediately assuming online preview is required.

4. **Tailscale / remote preview fallback**
   - Use Tailscale-hosted preview only as a fallback.
   - Do not assume the Tailscale preview path is reliable just because Tailscale is connected.
   - If remote preview fails, continue debugging the local preview/materialization path rather than treating remote failure as the primary issue.

### Important preview rule

Do **not** treat “preview unavailable” as a browser-only problem until you verify:

- preview materialization actually completed
- preview URL was actually produced
- preview URL was actually propagated into evaluator inputs
- local sandbox files exist where the manifest says they should exist
- the evaluator was not invoked too early before preview readiness

---

## Workspace-first artifact rules

When `workspace_manifest_v1` and `sandbox_ref` are present:

- Treat the manifest + sandbox files as the **authoritative artifact source**
- Avoid relying on duplicated inline `artifact_outputs[].content` unless explicitly debugging raw payload fallback
- Prefer reading the actual local files from the sandbox preview folder
- Be alert for token waste caused by sending both:
  - full inline HTML/CSS/JS content
  - and the same artifact via workspace manifest / sandbox reference

If debugging token inefficiency, check whether the system is duplicating:

- inline artifact bodies
- workspace-manifest references
- preview assembly inputs
- evaluator fallback code payloads

---

## OpenClaw agent/source-of-truth rules

The folder `docs\openclaw-agents` in this repo is a **representation** of the current agent files and supporting docs, but the **live runtime behavior may still come from**:

- `C:\Users\guestt\.openclaw`
- installed skills
- live gateway runtime config
- live browser / canvas / agent environment

When auditing planner/generator/evaluator behavior:

1. Check this repo's mirrored files first for intended behavior.
2. If behavior in logs does not match the mirrored docs, inspect `.openclaw` for drift.
3. Call out clearly whether the issue appears to be:
   - repo-side prompt/docs mismatch
   - live OpenClaw runtime mismatch
   - orchestrator-side wiring mismatch
   - preview/materialization/timing mismatch

Do not silently assume the repo mirror and the live OpenClaw installation are identical.

---

## Identity / crawl / planner debugging rules

When a run falls back into generic portfolio structure, check all of the following before assuming the generator is at fault:

- whether `selected_urls` is populated
- whether identity crawl evidence was actually captured
- whether that identity evidence reached planner inputs
- whether planner steps / evaluation targets still encode hero/projects/about/contact patterns
- whether evaluator targets mismatch the actual DOM
- whether iteration is refining the same structure due to routing, not creativity failure

If identity signals are weak, generic portfolio output is not surprising. Call that out explicitly.

---

## Evaluator debugging rules

When the evaluator reports issues, verify whether they are real against the actual local artifact before trusting them.

Especially verify:

- missing H1 / landmark claims
- selector mismatches
- motion/fallback checks
- preview_unavailable / missing_preview causes

Be careful about false negatives caused by:

- wrong artifact chosen
- stale artifact read
- preview URL missing even though local files exist
- DOM target mismatch between planner/evaluator and generator
- evaluator running before materialization completes

If the evaluator cannot access a live preview, prefer proving whether the fault is:
- preview generation
- preview propagation
- timing
- local path resolution
- browser invocation
rather than simply concluding “Playwright failed.”

---

## Runtime / orchestration debugging priorities

When reviewing logs, pay attention to:

- repeated polling of run detail endpoints
- repeated Supabase retry noise / `RemoteProtocolError`
- delayed or missing working-staging materialization
- preview readiness timing
- role invocation payload duplication
- unnecessary persistence of large raw artifact bodies
- interrupt timing / 409 conflicts
- event ordering problems that could cause evaluator to run before preview is actually ready

If something looks inefficient, distinguish between:

- root cause
- reinforcing factor
- harmless noise

---

## Preferred debugging style

When making changes or investigating issues:

- Prefer the **smallest high-confidence fix**
- Prefer **local-first verification**
- Preserve token discipline
- Do not expand scope unless necessary
- Add or update tests when behavior changes
- Be explicit about whether a problem is in:
  - orchestrator
  - live OpenClaw runtime
  - mirrored agent docs
  - workspace/materialization
  - evaluator parsing
  - planner/identity signals

---

## What "good" looks like

A healthy run should generally behave like this:

1. planner produces grounded structure from real identity evidence
2. generator writes preview artifacts into the local workspace/sandbox
3. preview is materialized locally
4. evaluator receives a usable preview target or a valid local fallback path
5. evaluator validates the real rendered artifact, not just duplicated inline code
6. iteration decisions are based on correct signals, not stale/missing preview state
7. token-heavy duplicate artifact flows are minimized

---

## If there is any ambiguity

If there is tension between:
- remote preview vs local preview
- repo mirror vs live OpenClaw files
- inline artifact body vs workspace manifest
- evaluator claim vs local HTML reality

prefer, in this order:

1. local materialized artifact reality
2. local orchestrator preview path
3. workspace manifest + sandbox files
4. live `.openclaw` runtime inspection
5. remote/Tailscale preview