"""
Scenario / gallery-strip visibility helpers (read-only, persisted payloads only).

Used by run list, proposals list, staging read models, and smoke scripts — no graph semantics.
"""

from __future__ import annotations

from typing import Any

# Must match seeds.SEEDED_*_SCENARIO_TAG / IDENTITY_URL_STATIC_FRONTEND_TAG
_GALLERY_TAG = "kmbl_seeded_gallery_strip_v1"
_GALLERY_VARIED_TAG = "kmbl_seeded_gallery_strip_varied_v1"
_KILOCLAW_IMAGE_ONLY_TEST_TAG = "kmbl_kiloclaw_image_only_test_v1"
_LOCAL_TAG = "kmbl_seeded_local_v1"
_IDENTITY_URL_STATIC_TAG = "kmbl_identity_url_static_v1"


def scenario_tag_from_run_state(snapshot: dict[str, Any] | None) -> str | None:
    """Extract ``event_input.scenario`` from a LangGraph checkpoint ``state_json`` (or sanitized API snapshot)."""
    if not snapshot:
        return None
    ev = snapshot.get("event_input")
    if isinstance(ev, dict):
        s = ev.get("scenario")
        return str(s) if s is not None else None
    return None


def scenario_badge_from_tag(tag: str | None) -> str | None:
    """
    Compact operator-facing label for list badges.

    Returns ``identity_url_static``, ``gallery_strip``, ``gallery_varied``,
    ``kiloclaw_image_test``, ``local_seed``, ``other``, or None.
    """
    if not tag:
        return None
    if tag == _IDENTITY_URL_STATIC_TAG:
        return "identity_url_static"
    if tag == _GALLERY_VARIED_TAG:
        return "gallery_varied"
    if tag == _GALLERY_TAG:
        return "gallery_strip"
    if tag == _KILOCLAW_IMAGE_ONLY_TEST_TAG:
        return "kiloclaw_image_test"
    if tag == _LOCAL_TAG:
        return "local_seed"
    return "other"


def gallery_strip_visibility_from_staging_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Derive inspection fields from staging ``snapshot_payload_json`` (v1 body).

    Does not mutate ``payload``.
    """
    meta = payload.get("metadata")
    wsp: dict[str, Any] = {}
    if isinstance(meta, dict):
        raw = meta.get("working_state_patch")
        if isinstance(raw, dict):
            wsp = raw
    strip = wsp.get("ui_gallery_strip_v1")
    has_strip = isinstance(strip, dict) and isinstance(strip.get("items"), list)
    items = strip.get("items") if isinstance(strip, dict) else []
    if not isinstance(items, list):
        items = []

    strip_item_count = len(items)
    items_with_artifact_key = 0
    for it in items:
        if isinstance(it, dict) and it.get("image_artifact_key"):
            items_with_artifact_key += 1

    arts = payload.get("artifacts")
    refs: list[Any] = []
    if isinstance(arts, dict):
        r = arts.get("artifact_refs")
        if isinstance(r, list):
            refs = r

    gallery_image_artifact_count = 0
    for a in refs:
        if isinstance(a, dict) and a.get("role") == "gallery_strip_image_v1":
            gallery_image_artifact_count += 1

    total_artifact_refs = len(refs)
    unlinked_image_slots = max(0, strip_item_count - items_with_artifact_key)

    return {
        "has_gallery_strip": has_strip,
        "gallery_strip_item_count": strip_item_count,
        "gallery_image_artifact_count": gallery_image_artifact_count,
        "total_artifact_refs": total_artifact_refs,
        "gallery_items_with_artifact_key": items_with_artifact_key,
        "gallery_items_unlinked_image_key": unlinked_image_slots,
    }


def static_frontend_visibility_from_staging_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Derive static HTML/CSS/JS artifact counts from staging ``snapshot_payload_json`` (v1).

    Prefer ``metadata.frontend_static`` when present; otherwise scan ``artifacts.artifact_refs``.
    """
    meta = payload.get("metadata")
    fs: dict[str, Any] | None = None
    if isinstance(meta, dict):
        raw = meta.get("frontend_static")
        if isinstance(raw, dict):
            fs = raw
    if fs and int(fs.get("file_count") or 0) > 0:
        return {
            "has_static_frontend": True,
            "static_frontend_file_count": int(fs.get("file_count", 0)),
            "static_frontend_bundle_count": int(fs.get("bundle_count", 0)),
            "has_previewable_html": bool(fs.get("has_previewable_html")),
        }

    arts = payload.get("artifacts")
    refs: list[Any] = []
    if isinstance(arts, dict):
        r = arts.get("artifact_refs")
        if isinstance(r, list):
            refs = r
    static_files: list[dict[str, Any]] = []
    for a in refs:
        if isinstance(a, dict) and a.get("role") == "static_frontend_file_v1":
            static_files.append(a)
    bundles: set[Any] = set()
    for a in static_files:
        b = a.get("bundle_id")
        bundles.add(b if isinstance(b, str) else None)
    has_html = any(
        str(a.get("language")) == "html" and a.get("previewable", True) for a in static_files
    )
    return {
        "has_static_frontend": len(static_files) > 0,
        "static_frontend_file_count": len(static_files),
        "static_frontend_bundle_count": len(bundles),
        "has_previewable_html": has_html,
    }
