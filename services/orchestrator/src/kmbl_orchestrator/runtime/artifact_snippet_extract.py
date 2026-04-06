"""
Bounded, deterministic text snippets from artifacts for model payloads when full bodies are omitted.
"""

from __future__ import annotations

import re
from typing import Any

# Hard budgets (characters, UTF-8 safe slicing by codepoints below)
DEFAULT_MAX_TOTAL: int = 9000
DEFAULT_HTML: int = 2800
DEFAULT_JS: int = 2200
DEFAULT_SHADER: int = 900


def _clip(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 20] + "\n…[truncated]…"


def _path(a: dict[str, Any]) -> str:
    return str(a.get("path") or a.get("file_path") or "")


def _content(a: dict[str, Any]) -> str:
    c = a.get("content")
    return c if isinstance(c, str) else ""


def extract_evaluator_snippets(
    artifacts: list[Any],
    *,
    max_total: int = DEFAULT_MAX_TOTAL,
    max_html: int = DEFAULT_HTML,
    max_js: int = DEFAULT_JS,
    max_shader: int = DEFAULT_SHADER,
) -> dict[str, Any]:
    """
    Return a compact dict: entry_html, scripts[], shaders[], note.

    Deterministic order: sort by path; first HTML entrypoint preferred.
    """
    arts = [a for a in artifacts if isinstance(a, dict)]
    arts.sort(key=lambda x: _path(x).lower())
    used = 0
    snippets: dict[str, Any] = {
        "snippet_version": 1,
        "entry_html": None,
        "scripts": [],
        "shaders": [],
        "note": (
            "Orchestrator-extracted snippets only — full artifacts are in persistence / preview URL; "
            "do not treat this as a complete bundle."
        ),
    }

    def budget(n: int) -> bool:
        nonlocal used
        if used + n > max_total:
            return False
        used += n
        return True

    # Prefer preview/index html
    html_candidates = [
        a
        for a in arts
        if _path(a).lower().endswith((".html", ".htm"))
    ]
    html_candidates.sort(
        key=lambda a: (
            0 if "preview/index.html" in _path(a).lower() else 1,
            len(_path(a)),
        )
    )
    for a in html_candidates:
        body = _content(a)
        if not body.strip():
            continue
        chunk = _clip(body, max_html)
        if not budget(len(chunk)):
            break
        snippets["entry_html"] = {"path": _path(a), "text": chunk}
        break

    for a in arts:
        p = _path(a).lower()
        if not p.endswith(".js"):
            continue
        body = _content(a)
        if not body.strip():
            continue
        chunk = _clip(body, max_js)
        if not budget(len(chunk)):
            break
        snippets["scripts"].append({"path": _path(a), "text": chunk})
        if len(snippets["scripts"]) >= 2:
            break

    shader_exts = (".wgsl", ".glsl", ".vert", ".frag")
    for a in arts:
        p = _path(a).lower()
        if not p.endswith(shader_exts):
            continue
        body = _content(a)
        if not body.strip():
            continue
        # Prefer header / first directive block
        head = body[: max_shader * 2]
        m = re.search(r"^[\s\S]{0,400}", head)
        chunk = _clip(m.group(0) if m else head, max_shader)
        if not budget(len(chunk)):
            break
        snippets["shaders"].append({"path": _path(a), "text": chunk})
        if len(snippets["shaders"]) >= 4:
            break

    return snippets


def extract_failure_focus_snippets(
    artifacts: list[Any],
    *,
    substring_needles: list[str],
    per_file_margin: int = 180,
    max_files: int = 3,
    max_per_snippet: int = 1200,
) -> list[dict[str, Any]]:
    """
    For literal / compliance debugging: small windows around first needle hit per file.
    """
    arts = [a for a in artifacts if isinstance(a, dict)]
    needles = [n for n in substring_needles if isinstance(n, str) and n.strip()]
    if not needles:
        return []
    out: list[dict[str, Any]] = []
    for a in arts:
        if len(out) >= max_files:
            break
        body = _content(a)
        if not body:
            continue
        low = body.lower()
        pos: int | None = None
        needle_hit: str | None = None
        for n in needles:
            idx = low.find(n.lower())
            if idx >= 0:
                needle_hit, pos = n, idx
                break
        if pos is None or needle_hit is None:
            continue
        start = max(0, pos - per_file_margin)
        end = min(len(body), pos + len(needle_hit) + per_file_margin)
        snippet = body[start:end]
        out.append(
            {
                "path": _path(a),
                "needle": needle_hit,
                "text": _clip(snippet, max_per_snippet),
            }
        )
    return out
