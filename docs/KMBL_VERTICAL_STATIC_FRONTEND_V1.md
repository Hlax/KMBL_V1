# KMBL Vertical: Static Frontend V1

## Overview

The **static frontend vertical** is the canonical proof path for KMBL V1. It takes
an identity source (website URL), extracts signals, and produces a self-contained
static HTML/CSS/JS package that reflects the extracted identity.

## Canonical Flow

```
Identity URL
  → Website fetch & extraction
  → Identity seed (IdentitySeed schema)
  → Persisted identity records (IdentitySourceRecord + IdentityProfileRecord)
  → Planner (build_spec with canonical_vertical = "static_frontend_file_v1")
  → Generator (static_frontend_file_v1 artifacts under component/)
  → Evaluator (lightweight: presence + structure checks)
  → BuildCandidateRecord (normalized artifacts)
  → Staging node: apply to working_staging (mutable); optional StagingSnapshot per policy
  → [If review snapshot row exists] Static preview (GET /orchestrator/staging/{id}/static-preview)
```

**Review snapshot row:** Not every stage produces a `staging_snapshot` row. Persistence follows **`KMBL_STAGING_SNAPSHOT_POLICY`** (`always` | `on_nomination` | `never`) and evaluator nomination when `on_nomination`. When skipped, **`staging_snapshot_skipped`** is recorded; **working staging** still updates. Operators can **materialize** a frozen review row from live working staging (`POST /orchestrator/working-staging/{thread_id}/review-snapshot`). See [`CURRENT_PRODUCT_MODEL.md`](CURRENT_PRODUCT_MODEL.md).

## Artifact Contract

### `static_frontend_file_v1`

The primary artifact role for this vertical. Each row represents one file in a
static HTML/CSS/JS bundle.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `role` | string | yes | `"static_frontend_file_v1"` |
| `path` | string | yes | Relative path under `component/` (e.g. `component/preview/index.html`) |
| `language` | `"html" \| "css" \| "js"` | yes | File type (inferred from extension if omitted) |
| `content` | string | yes | File content (non-empty, max 256KB) |
| `bundle_id` | string \| null | no | Groups files into one reviewable bundle |
| `previewable` | boolean \| null | no | Defaults to `true` for HTML |
| `entry_for_preview` | boolean | no | Exactly one per bundle for preview assembly |

### Path rules

- Must start with `component/`
- Must match `component/<segments>/<name>.html|.css|.js`
- No `..`, no absolute paths, no `//`
- Language must match file extension

### Recovery promotion

If the generator places file entries in `proposed_changes` (matching
`component/**/*.{html,css,js}` with non-empty content) but leaves `artifact_outputs`
empty of static frontend rows, KMBL promotes them into `static_frontend_file_v1`
artifacts as a safety net. This is not the intended contract path — generators should
always emit files directly in `artifact_outputs`.

## Planner Contract

For this vertical, the planner should:

- Set `constraints.canonical_vertical` to `"static_frontend_file_v1"`
- Set `constraints.kmbl_static_frontend_vertical` to `true`
- Include preview-checkable `success_criteria` (visible text, structural markers)
- Include `evaluation_targets` with `text_present` or `selector_present` checks

## Generator Contract

The generator should:

- Emit at least one `static_frontend_file_v1` row in `artifact_outputs`
- At minimum: one `.html` file with non-empty content
- Optionally: `.css` and `.js` siblings
- Keep markup self-contained (no external framework CDNs required)
- Use relative paths between `component/` files

## Evaluator Contract (Lightweight)

For this stage, the evaluator should:

- Check that `artifact_outputs` contains at least one `static_frontend_file_v1` row
- Check that HTML content is non-empty and structurally valid
- Check for basic identity alignment (if identity context was provided)
- Report `pass` when output is present and structurally valid
- Report `partial` when output exists but has gaps
- Report `fail` only when output is empty, malformed, or completely unrelated
- Report `blocked` only when evaluation cannot proceed honestly

The evaluator should NOT:

- Apply strict aesthetic scoring at this stage
- Require pixel-perfect design rubric scores
- Block on missing optional fields
- Over-index on subjective quality metrics

## Staging & Preview

Staging snapshots include `metadata.frontend_static` derived from persisted
`static_frontend_file_v1` artifacts. The static preview endpoint
(`GET /orchestrator/staging/{id}/static-preview`) assembles inline HTML from the
persisted bundle (CSS/JS inlined into the entry HTML file).

## Identity Seed Schema

The identity seed extracted from a website URL:

| Field | Type | Description |
|-------|------|-------------|
| `source_url` | string | The source website URL |
| `display_name` | string \| null | Inferred name/brand |
| `role_or_title` | string \| null | Inferred role or professional title |
| `short_bio` | string \| null | Brief description |
| `tone_keywords` | string[] | Detected tone signals |
| `aesthetic_keywords` | string[] | Design/layout cues |
| `palette_hints` | string[] | Color values found |
| `layout_hints` | string[] | Layout structure cues |
| `project_evidence` | string[] | Work/project references |
| `image_refs` | string[] | Image URLs found |
| `headings` | string[] | Page headings (H1–H3) |
| `meta_description` | string \| null | Meta description tag |
| `extraction_notes` | string[] | Warnings or degradation notes |
| `confidence` | float | 0.0–1.0 extraction quality estimate |

All fields are optional except `source_url`. A partial seed is always valid.

## Future Expansion

This vertical is designed to later support:

- Multi-page identity extraction
- Richer visual extraction from site imagery
- Image remixing or transformation via kmbl-image-gen
- Gallery expansion with `gallery_strip_image_v1`
- Gaussian splat / 3D identity capture
- Stronger evaluator grading loops
- Design rubric scoring (after generation is reliable)
