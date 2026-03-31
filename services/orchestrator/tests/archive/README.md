# Archived Tests

These tests were moved out of the active test suite during the canonical vertical
refactoring. They test gallery-specific, image-provider, or stability paths that are
not part of the current canonical vertical (identity URL → static frontend).

They are preserved for future reference and potential reactivation when gallery/image
capabilities expand beyond the current additive role.

## Archived files

- `test_gallery_strip_harness.py` — Gallery strip harness metrics merging (can downgrade pass → partial)
- `test_gallery_variation_pass.py` — Gallery variation bounded seeds and presets
- `test_image_provider_pass.py` — Legacy orchestrator-side OpenAI image provider (disabled in config)
- `test_smoke_stability.py` — Gallery smoke stability helpers

## Why archived (not deleted)

These tests validate real code paths that still exist in the codebase. The gallery
normalization code (`ui_gallery_strip_v1`, `gallery_image_artifact_v1`) remains active
as an additive capability. These tests were archived because:

1. They enforce gallery-specific pass/fail criteria that don't apply to the canonical vertical
2. They reference scenario presets (gallery strip, image-only) outside the primary test lane
3. They can cause false negatives when run against the canonical static frontend path
