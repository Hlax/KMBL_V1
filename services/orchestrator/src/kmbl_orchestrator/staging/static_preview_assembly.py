"""
Assemble a single HTML document for operator preview of ``static_frontend_file_v1`` artifacts.

Uses only normalized rows from persisted staging ``snapshot_payload_json`` — no filesystem,
no raw KiloClaw blobs. Entry path resolution matches :func:`derive_frontend_static_v1`.
"""

from __future__ import annotations

import re
from typing import Any

from kmbl_orchestrator.staging.build_snapshot import derive_frontend_static_v1

# Stable machine-readable reasons for HTTP 404 JSON bodies
NO_STATIC_ARTIFACTS = "no_static_frontend_artifacts"
NO_PREVIEWABLE_HTML = "no_previewable_html"
NO_PREVIEW_ENTRY = "no_preview_entry"
BUNDLE_NOT_FOUND = "bundle_not_found"
BUNDLE_NO_ENTRY = "bundle_has_no_entry"
ENTRY_NOT_HTML = "entry_not_html"
ENTRY_CONTENT_MISSING = "entry_content_missing"


def _artifact_refs_from_payload(payload: dict[str, Any]) -> list[Any]:
    arts = payload.get("artifacts")
    if not isinstance(arts, dict):
        return []
    refs = arts.get("artifact_refs")
    return list(refs) if isinstance(refs, list) else []


def _working_state_patch_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    meta = payload.get("metadata")
    if not isinstance(meta, dict):
        return {}
    wsp = meta.get("working_state_patch")
    return dict(wsp) if isinstance(wsp, dict) else {}


def static_file_map_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    """
    ``path`` -> ``content`` for ``static_frontend_file_v1`` rows only (validated shape).
    """
    out: dict[str, str] = {}
    for a in _artifact_refs_from_payload(payload):
        if not isinstance(a, dict) or a.get("role") != "static_frontend_file_v1":
            continue
        path = a.get("path")
        content = a.get("content")
        lang = a.get("language")
        if not isinstance(path, str) or not path.strip():
            continue
        if not isinstance(content, str):
            continue
        p = path.strip().replace("\\", "/")
        if not p.startswith("component/"):
            continue
        if lang not in ("html", "css", "js", "json", "glsl", "wgsl"):
            continue
        out[p] = content
    return out


def static_artifact_meta_by_path(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """path -> raw artifact dict for static_frontend_file_v1 rows."""
    out: dict[str, dict[str, Any]] = {}
    for a in _artifact_refs_from_payload(payload):
        if not isinstance(a, dict) or a.get("role") != "static_frontend_file_v1":
            continue
        path = a.get("path")
        if isinstance(path, str) and path.strip():
            out[path.strip().replace("\\", "/")] = a
    return out


def resolve_static_preview_entry_path(
    payload: dict[str, Any],
    *,
    bundle_id: str | None = None,
) -> tuple[str | None, str]:
    """
    Return ``(entry_path, error_code)`` where ``error_code`` is empty on success.

    ``bundle_id`` selects a bundle when multiple exist; otherwise the first bundle with a
    resolved preview entry is used (deterministic order from ``derive_frontend_static_v1``).
    """
    refs = _artifact_refs_from_payload(payload)
    wsp = _working_state_patch_from_payload(payload)
    fs = derive_frontend_static_v1(refs, wsp)
    if fs is None:
        return None, NO_STATIC_ARTIFACTS
    if not fs.has_previewable_html:
        return None, NO_PREVIEWABLE_HTML

    bundles = list(fs.bundles)
    if not bundles:
        return None, NO_PREVIEW_ENTRY

    if bundle_id is not None:
        for b in bundles:
            bid = b.bundle_id
            if (bid or None) == bundle_id:
                if b.preview_entry_path:
                    return b.preview_entry_path, ""
                return None, BUNDLE_NO_ENTRY
        return None, BUNDLE_NOT_FOUND

    for b in sorted(bundles, key=lambda x: (x.bundle_id is None, x.bundle_id or "")):
        if b.preview_entry_path:
            return b.preview_entry_path, ""

    return None, NO_PREVIEW_ENTRY


def _inject_css_and_js(html: str, css_chunks: list[str], js_chunks: list[str]) -> str:
    style_tags = "".join(
        f'<style type="text/css" data-kmbl-injected="true">\n{c}\n</style>\n'
        for c in css_chunks
        if c.strip()
    )
    script_tags = "".join(
        f'<script data-kmbl-injected="true">\n{c}\n</script>\n'
        for c in js_chunks
        if c.strip()
    )
    if style_tags:
        low = html.lower()
        if "</head>" in low:
            i = low.rfind("</head>")
            html = html[:i] + style_tags + html[i:]
        else:
            html = style_tags + html
    if script_tags:
        low = html.lower()
        if "</body>" in low:
            i = low.rfind("</body>")
            html = html[:i] + script_tags + html[i:]
        else:
            html = html + "\n" + script_tags
    return html


def assemble_static_preview_html(
    payload: dict[str, Any],
    *,
    entry_path: str,
) -> tuple[str | None, str]:
    """
    Build one self-contained HTML string with sibling CSS/JS from the same bundle inlined.

    Returns ``(html, error_code)``.
    """
    files = static_file_map_from_payload(payload)
    meta_by_path = static_artifact_meta_by_path(payload)
    ep = entry_path.strip().replace("\\", "/")
    if ep not in files:
        return None, ENTRY_CONTENT_MISSING
    entry_art = meta_by_path.get(ep) or {}
    if str(entry_art.get("language")) != "html":
        return None, ENTRY_NOT_HTML

    entry_html = files[ep]
    bid = entry_art.get("bundle_id")
    bundle_key: str | None = bid if isinstance(bid, str) else None

    def same_bundle(p: str) -> bool:
        a = meta_by_path.get(p) or {}
        b = a.get("bundle_id")
        other: str | None = b if isinstance(b, str) else None
        return other == bundle_key

    css_chunks: list[str] = []
    js_chunks: list[str] = []
    for path in sorted(files.keys()):
        if path == ep:
            continue
        if not same_bundle(path):
            continue
        lang = (meta_by_path.get(path) or {}).get("language")
        if lang == "css":
            css_chunks.append(f"/* {path} */\n{files[path]}")
        elif lang == "js":
            js_chunks.append(f"/* {path} */\n{files[path]}")

    # Strip same-bundle link/script tags that point to known artifact paths (avoid double load)
    cleaned = entry_html
    for path in files:
        if not same_bundle(path) or path == ep:
            continue
        fname = path.rsplit("/", 1)[-1]
        cleaned = re.sub(
            rf'<link[^>]*href=["\']{re.escape(fname)}["\'][^>]*>',
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            rf'<script[^>]*src=["\']{re.escape(fname)}["\'][^>]*>\s*</script>',
            "",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )

    out = _inject_css_and_js(cleaned, css_chunks, js_chunks)
    return out, ""
