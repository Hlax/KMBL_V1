"""Live habitat preview hints — uses existing static preview resolution without duplicating HTML assembly."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.staging.build_snapshot import derive_frontend_static_v1
from kmbl_orchestrator.staging.static_preview_assembly import (
    _artifact_refs_from_payload,
    _working_state_patch_from_payload,
    resolve_static_preview_entry_path,
    static_file_map_from_payload,
)


def _block_preview_anchors_from_payload(payload: dict[str, Any]) -> list[str]:
    meta = payload.get("metadata")
    if not isinstance(meta, dict):
        return []
    raw = meta.get("block_preview_anchors")
    if isinstance(raw, list):
        return [str(x) for x in raw if isinstance(x, str) and x.strip()]
    wsp = meta.get("working_state_patch")
    if isinstance(wsp, dict):
        raw2 = wsp.get("block_preview_anchors")
        if isinstance(raw2, list):
            return [str(x) for x in raw2 if isinstance(x, str) and x.strip()]
    return []


def live_habitat_preview_surface(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Structured hints for the live working-staging surface (paths, bundles, anchors).

    Uses the same resolution rules as resolve_static_preview_entry_path and
    derive_frontend_static_v1 — no duplicate HTML assembly.
    """
    refs = _artifact_refs_from_payload(payload)
    wsp = _working_state_patch_from_payload(payload)
    entry, err = resolve_static_preview_entry_path(payload)
    files = static_file_map_from_payload(payload)
    html_paths = sorted(p for p in files if isinstance(p, str) and p.lower().endswith(".html"))

    bundles_out: list[dict[str, Any]] = []
    fs = derive_frontend_static_v1(refs, wsp)
    if fs is not None:
        for b in fs.bundles:
            bundles_out.append(
                {
                    "bundle_id": b.bundle_id,
                    "preview_entry_path": b.preview_entry_path,
                    "file_paths": list(b.file_paths),
                }
            )

    return {
        "default_entry_path": entry,
        "preview_error": err or None,
        "html_paths": html_paths,
        "bundles": bundles_out,
        "block_preview_anchors": _block_preview_anchors_from_payload(payload),
    }
