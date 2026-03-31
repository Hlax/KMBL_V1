"""HTML block merge engine — apply ``html_block_v1`` artifacts to existing HTML files.

Blocks are applied using a lightweight tag-depth scanner (Python stdlib only).
Handles the common case of block-level elements identified by an ``id`` attribute.

Supported operations:
- ``replace``: Replace the element whose ``id`` matches the id in ``target_selector``.
- ``append_to_body``: Insert content just before ``</body>``.
- ``prepend_to_body``: Insert content immediately after the opening ``<body ...>`` tag.

When a ``replace`` target element is not found, the block content is appended to
``<body>`` as a safe fallback (so generators producing blocks for a fresh page
don't produce an empty result).

Usage::

    from kmbl_orchestrator.staging.block_merge import apply_blocks_to_static_files
    from kmbl_orchestrator.contracts.html_block_artifact_v1 import HtmlBlockArtifactV1

    merged_map, anchors = apply_blocks_to_static_files(blocks, file_map)
    # merged_map: path → merged html (only files that changed)
    # anchors: list[str] of effective preview_anchor values (first anchor is primary)
"""

from __future__ import annotations

import logging
import re
from typing import Any

_log = logging.getLogger(__name__)

# Minimal HTML skeleton for a target file that doesn't exist yet
_MINIMAL_HTML_TEMPLATE = (
    "<!DOCTYPE html>\n"
    "<html lang=\"en\">\n"
    "<head>\n"
    "  <meta charset=\"utf-8\">\n"
    "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
    "  <title>Preview</title>\n"
    "</head>\n"
    "<body>\n"
    "</body>\n"
    "</html>\n"
)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def apply_blocks_to_static_files(
    blocks: list[Any],
    file_map: dict[str, str],
) -> tuple[dict[str, str], list[str]]:
    """Apply a list of ``HtmlBlockArtifactV1`` objects to a set of HTML files.

    Parameters
    ----------
    blocks:
        Validated ``HtmlBlockArtifactV1`` objects (or dicts with equivalent shape).
    file_map:
        Mapping of ``path → current HTML content`` from the working staging.
        Paths not present are treated as new files and seeded from the minimal template.

    Returns
    -------
    merged_map:
        ``path → merged HTML`` for **only the files that were modified**.
        Callers should update the staging artifact_refs with these new contents.
    anchors:
        Ordered list of ``effective_preview_anchor`` values (one per applied block).
        The first anchor is the primary preview anchor for the staging URL.
    """
    # Group blocks by target_path
    by_path: dict[str, list[Any]] = {}
    for block in blocks:
        tp = _get(block, "target_path", "")
        if isinstance(tp, str) and tp:
            by_path.setdefault(tp, []).append(block)

    merged_map: dict[str, str] = {}
    anchors: list[str] = []

    for path, path_blocks in by_path.items():
        current_html = file_map.get(path, _MINIMAL_HTML_TEMPLATE)
        merged_html = current_html

        for block in path_blocks:
            op = _get(block, "operation", "replace")
            selector = _get(block, "target_selector", "__body__")
            content = _get(block, "content", "")

            try:
                if op == "replace":
                    merged_html = _apply_replace(merged_html, selector, content)
                elif op == "append_to_body":
                    merged_html = _apply_append_to_body(merged_html, content)
                elif op == "prepend_to_body":
                    merged_html = _apply_prepend_to_body(merged_html, content)
                else:
                    _log.warning("html_block merge: unknown operation %r, skipping", op)
                    continue
            except Exception as exc:
                _log.warning(
                    "html_block merge failed path=%s block_id=%s op=%s: %s",
                    path,
                    _get(block, "block_id", "?"),
                    op,
                    exc,
                )
                continue

            # Record anchor
            anchor = _effective_anchor(block)
            if anchor:
                anchors.append(anchor)

        if merged_html != current_html or path not in file_map:
            merged_map[path] = merged_html

    return merged_map, anchors


def apply_html_block(html_content: str, block: Any) -> str:
    """Apply a single ``html_block_v1`` (or equivalent dict) to ``html_content``.

    Convenience wrapper over :func:`apply_blocks_to_static_files` for single-block
    use in tests and direct callers.
    """
    target_path = _get(block, "target_path", "component/preview/index.html")
    merged_map, _ = apply_blocks_to_static_files([block], {target_path: html_content})
    return merged_map.get(target_path, html_content)


# ─────────────────────────────────────────────────────────────────────────────
# Operations
# ─────────────────────────────────────────────────────────────────────────────

def _apply_replace(html: str, selector: str, new_content: str) -> str:
    """Replace the element selected by ``selector`` with ``new_content``.

    ``selector`` must be a CSS id selector (``#hero``) or ``__body__``.
    When the target element is not found, ``new_content`` is appended to ``<body>``
    so the generator's work is never silently discarded.
    """
    if selector == "__body__":
        return _apply_append_to_body(html, new_content)

    if selector.startswith("#"):
        element_id = selector.lstrip("#")
        result = _replace_element_by_id(html, element_id, new_content)
        if result is not None:
            return result
        # Fallback: target not found, append to body
        _log.info(
            "html_block replace: element #%s not found in existing HTML, "
            "appending to body as fallback",
            element_id,
        )
        return _apply_append_to_body(html, new_content)

    # Unrecognised selector format — safe fallback
    _log.warning(
        "html_block replace: unrecognised selector %r, appending to body", selector
    )
    return _apply_append_to_body(html, new_content)


def _apply_append_to_body(html: str, content: str) -> str:
    """Insert ``content`` immediately before ``</body>``."""
    lower = html.lower()
    pos = lower.rfind("</body>")
    if pos == -1:
        return html + "\n" + content
    return html[:pos] + content + "\n" + html[pos:]


def _apply_prepend_to_body(html: str, content: str) -> str:
    """Insert ``content`` immediately after the opening ``<body ...>`` tag."""
    body_re = re.compile(r"<body(?:\s[^>]*)?>", re.IGNORECASE)
    m = body_re.search(html)
    if m is None:
        return content + "\n" + html
    insert_pos = m.end()
    return html[:insert_pos] + "\n" + content + html[insert_pos:]


# ─────────────────────────────────────────────────────────────────────────────
# Element replacement (id-based, tag-depth scanner)
# ─────────────────────────────────────────────────────────────────────────────

# Matches the opening tag of an element whose id attribute equals the target.
# Captures the tag name (group 1).
def _make_open_tag_re(element_id: str) -> re.Pattern[str]:
    eid = re.escape(element_id)
    return re.compile(
        r"<([a-z][a-z0-9-]*)\b(?=[^>]*\bid=[\"']"
        + eid
        + r"[\"'])[^>]*>",
        re.IGNORECASE | re.DOTALL,
    )


def _replace_element_by_id(
    html: str,
    element_id: str,
    new_content: str,
) -> str | None:
    """Replace the HTML element whose ``id`` equals ``element_id``.

    Returns the modified HTML string, or ``None`` if the element was not found.
    Handles nested same-tag elements correctly using a depth counter.
    """
    open_re = _make_open_tag_re(element_id)
    m = open_re.search(html)
    if m is None:
        return None

    tag_name = m.group(1).lower()
    start = m.start()
    after_open = m.end()

    end = _find_closing_tag_end(html, after_open, tag_name)
    if end is None:
        # Self-closing or unclosed element: replace just the opening tag span
        return html[:start] + new_content + html[after_open:]

    return html[:start] + new_content + html[end:]


def _find_closing_tag_end(html: str, start: int, tag_name: str) -> int | None:
    """Find the end position (exclusive) of the closing tag for ``tag_name``.

    Starts scanning from ``start`` with depth=1 (already inside the opening tag).
    Returns ``None`` if no matching closing tag is found.
    """
    open_re = re.compile(r"<" + re.escape(tag_name) + r"\b", re.IGNORECASE)
    close_re = re.compile(r"</" + re.escape(tag_name) + r"\s*>", re.IGNORECASE)

    depth = 1
    pos = start
    length = len(html)

    while depth > 0 and pos < length:
        next_open = open_re.search(html, pos)
        next_close = close_re.search(html, pos)

        if next_close is None:
            return None  # malformed HTML

        if next_open is not None and next_open.start() < next_close.start():
            depth += 1
            pos = next_open.end()
        else:
            depth -= 1
            if depth == 0:
                return next_close.end()
            pos = next_close.end()

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Get a value from either a dict or a Pydantic model."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _effective_anchor(block: Any) -> str:
    """Derive the effective preview anchor for a block (dict or model)."""
    # Try the model property first (Pydantic model)
    try:
        return block.effective_preview_anchor  # type: ignore[union-attr]
    except AttributeError:
        pass
    # Fall back to dict logic
    pa = _get(block, "preview_anchor")
    if isinstance(pa, str) and pa.strip():
        return pa.strip().lstrip("#")
    sel = _get(block, "target_selector", "")
    if isinstance(sel, str) and sel.startswith("#"):
        return sel.lstrip("#")
    bid = _get(block, "block_id", "")
    return str(bid) if bid else ""
