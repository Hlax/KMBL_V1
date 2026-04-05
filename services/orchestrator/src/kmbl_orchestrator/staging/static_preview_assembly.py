"""
Assemble a single HTML document for operator preview of static / interactive frontend file artifacts.

Uses only normalized rows from persisted staging ``snapshot_payload_json`` — no filesystem,
no raw KiloClaw blobs. Entry path resolution matches :func:`derive_frontend_static_v1`.

**Interactive / multi-file JS:** Sibling ``.js`` files are merged into one document by stripping
``<script src=...>`` tags and injecting sources. Injection order is:

1. Optional explicit ``kmbl_preview_assembly_hints_v1.js_path_order`` in ``working_state_patch``
   (full ``component/...`` paths, subset of same-bundle JS).
2. Otherwise, DOM order of ``<script src=...>`` in the entry HTML (basename match).
3. Any remaining same-bundle JS paths, sorted by path for stability.

``type="module"`` on a ``<script src=...>`` tag is preserved on the injected block for that file.
Cross-file ``import`` between separate artifact JS files is **not** resolved — prefer a single
bundled script or a CDN for complex module graphs.
"""

from __future__ import annotations

import re
from typing import Any

from kmbl_orchestrator.contracts.frontend_artifact_roles import is_frontend_file_artifact_role
from kmbl_orchestrator.staging.build_snapshot import derive_frontend_static_v1

# Stable machine-readable reasons for HTTP 404 JSON bodies
NO_STATIC_ARTIFACTS = "no_static_frontend_artifacts"
NO_PREVIEWABLE_HTML = "no_previewable_html"
NO_PREVIEW_ENTRY = "no_preview_entry"
BUNDLE_NOT_FOUND = "bundle_not_found"
BUNDLE_NO_ENTRY = "bundle_has_no_entry"
ENTRY_NOT_HTML = "entry_not_html"
ENTRY_CONTENT_MISSING = "entry_content_missing"

_SCRIPT_OPEN_RE = re.compile(r"<script\b([^>]*)>", re.IGNORECASE | re.DOTALL)


def _basename_from_url(src: str) -> str:
    s = src.strip().split("#", 1)[0].split("?", 1)[0]
    return s.rsplit("/", 1)[-1].lower() if s else ""


def _hints_js_path_order(wsp: dict[str, Any]) -> list[str]:
    h = wsp.get("kmbl_preview_assembly_hints_v1")
    if not isinstance(h, dict):
        return []
    raw = h.get("js_path_order")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        if isinstance(x, str) and x.strip():
            out.append(x.strip().replace("\\", "/"))
    return out


def _dom_js_order_and_module_flags(
    entry_html: str,
    js_paths: list[str],
) -> tuple[list[str], dict[str, bool]]:
    """Order ``js_paths`` by first matching ``<script src=`` in entry HTML; module flag per path."""
    path_by_base: dict[str, str] = {}
    for p in js_paths:
        path_by_base[p.rsplit("/", 1)[-1].lower()] = p

    bases_order: list[str] = []
    mod_by_base: dict[str, bool] = {}
    for m in _SCRIPT_OPEN_RE.finditer(entry_html):
        tag_inner = m.group(1)
        src_m = re.search(r"\bsrc\s*=\s*[\"']([^\"']+)[\"']", tag_inner, re.I)
        if not src_m:
            continue
        base = _basename_from_url(src_m.group(1))
        full = path_by_base.get(base)
        if not full:
            continue
        if base not in bases_order:
            bases_order.append(base)
        is_mod = bool(re.search(r"type\s*=\s*[\"']?\s*module", tag_inner, re.I))
        mod_by_base[base] = mod_by_base.get(base, False) or is_mod

    ordered_paths = [path_by_base[b] for b in bases_order]
    mod_by_path: dict[str, bool] = {}
    for p in js_paths:
        b = p.rsplit("/", 1)[-1].lower()
        mod_by_path[p] = mod_by_base.get(b, False)
    return ordered_paths, mod_by_path


def _merge_js_path_order(
    js_paths: list[str],
    explicit: list[str],
    dom_paths: list[str],
) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in explicit + dom_paths:
        if p in js_paths and p not in seen:
            out.append(p)
            seen.add(p)
    for p in sorted(set(js_paths) - seen):
        out.append(p)
    return out


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
    ``path`` -> ``content`` for static / interactive frontend file rows (validated shape).
    """
    out: dict[str, str] = {}
    for a in _artifact_refs_from_payload(payload):
        if not isinstance(a, dict) or not is_frontend_file_artifact_role(a.get("role")):
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
    """path -> raw artifact dict for static / interactive frontend file rows."""
    out: dict[str, dict[str, Any]] = {}
    for a in _artifact_refs_from_payload(payload):
        if not isinstance(a, dict) or not is_frontend_file_artifact_role(a.get("role")):
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


def _inject_css_and_js(
    html: str,
    css_chunks: list[str],
    js_chunks: list[tuple[str, bool]],
) -> str:
    """``js_chunks`` items are ``(content, use_module_type)`` — module flag from entry HTML."""
    style_tags = "".join(
        f'<style type="text/css" data-kmbl-injected="true">\n{c}\n</style>\n'
        for c in css_chunks
        if c.strip()
    )
    script_parts: list[str] = []
    for c, is_module in js_chunks:
        if not c.strip():
            continue
        mod = ' type="module"' if is_module else ""
        script_parts.append(f"<script{mod} data-kmbl-injected=\"true\">\n{c}\n</script>\n")
    script_tags = "".join(script_parts)
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
    wsp = _working_state_patch_from_payload(payload)

    def same_bundle(p: str) -> bool:
        a = meta_by_path.get(p) or {}
        b = a.get("bundle_id")
        other: str | None = b if isinstance(b, str) else None
        return other == bundle_key

    css_chunks: list[str] = []
    for path in sorted(files.keys()):
        if path == ep:
            continue
        if not same_bundle(path):
            continue
        lang = (meta_by_path.get(path) or {}).get("language")
        if lang == "css":
            css_chunks.append(f"/* {path} */\n{files[path]}")

    js_only_paths = [
        p
        for p in files
        if p != ep
        and same_bundle(p)
        and (meta_by_path.get(p) or {}).get("language") == "js"
    ]
    explicit = _hints_js_path_order(wsp)
    dom_paths, mod_by_path = _dom_js_order_and_module_flags(entry_html, js_only_paths)
    merged_js = _merge_js_path_order(js_only_paths, explicit, dom_paths)
    js_chunks: list[tuple[str, bool]] = [
        (f"/* {path} */\n{files[path]}", bool(mod_by_path.get(path, False)))
        for path in merged_js
    ]

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
