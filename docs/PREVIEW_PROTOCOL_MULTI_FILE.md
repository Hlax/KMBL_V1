# Multi-file / app-like preview protocol (orchestrator contract)

This defines a **single mental model** for how **multi-file** or **bundled** generator output is **previewed**, **staged**, and **evaluated** in KMBL. The orchestrator already has vertical-specific hooks (`interactive_frontend_app_v1`, manifest-first static, working-staging preview assembly). This document ties them together so operators and agents share one protocol.

## Goals

1. **One primary entry** — A deterministic URL path (relative to the workspace or staging tree) that loads the experience (e.g. `index.html` or `component/preview/index.html`).
2. **Explicit build step (optional)** — If the generator uses a bundler, the manifest or `workspace_context` should record **how** artifacts were produced (even if only “static files, no bundler”). The orchestrator evaluates **artifacts on disk** after ingest, not the build tool itself.
3. **Health before LLM judge** — **Static preview assembly** and **CSP** (orchestrator) establish a baseline “does this load”. **Evaluator** gates (literal checks, duplicate staging, interactive lane) run on **resolved artifact text** and optional preview hints — not on arbitrary remote URLs.

## Layers

| Layer | Responsibility |
|--------|------------------|
| **Workspace** | Generator writes under `KMBL_GENERATOR_WORKSPACE_ROOT` with `workspace_manifest_v1` + `sandbox_ref` when using disk-first output. |
| **Ingest** | `workspace_ingest` merges files into `artifact_outputs` for persistence and staging. |
| **Working staging** | Mutable `working_staging.payload_json` + static preview assembly for the iframe (`/orchestrator/working-staging/{thread_id}/preview`). |
| **Evaluator** | Gates on artifact content + preview resolution (`session_staging_links`, preview surface gates). |

## Lightweight interactivity vs heavy runtime

- **Lightweight (in scope for v1 preview):** static HTML + CSS + inline or single-file JS; CDN scripts from allowlists (see habitat CDNs / CSP); single **Three.js** or **canvas** scene with bounded asset size.
- **Heavy (out of band unless extended):** long-running `npm dev` servers, arbitrary WebSockets backends, auth flows, or unbounded dependency trees. These require a **dedicated preview runner** and stricter resource limits — not assumed by default static preview.

## Alignment with code

- Workspace paths: `kmbl_orchestrator.runtime.workspace_paths` — `build_workspace_context_for_generator`, canonical preview entry.
- Interactive vertical: `kmbl_orchestrator.runtime.interactive_lane_context` / `interactive_lane_evaluator_gate`.
- Preview CSP: orchestrator `routes_working_staging` preview handler.

When adding a new vertical, extend **one** of: manifest schema, `surface_type`, or interactive lane flags — and document the **entry path** and **evaluator expectations** here in a short subsection.
