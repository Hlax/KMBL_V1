"""
Deterministic ``build_candidate_summary_v1`` — compact orchestrator-built summary of generated artifacts.

Full ``artifact_outputs`` / ``artifact_refs_json`` remain the source of truth in persistence;
this structure is for downstream model payloads and operator visibility only.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from kmbl_orchestrator.contracts.frontend_artifact_roles import is_frontend_file_artifact_role
from kmbl_orchestrator.runtime.generator_library_policy import GAUSSIAN_SPLAT_LIBRARY_PRIMARY
from kmbl_orchestrator.runtime.static_vertical_invariants import is_interactive_frontend_vertical

SUMMARY_VERSION: int = 1

# Strict artifact evidence: import/from, runtime API, or known CDN script URLs (not spec mentions).
_LIB_PATTERNS_ARTIFACT: tuple[tuple[str, str], ...] = (
    (
        "three",
        r"(?:from|import)\s+['\"]three['\"]|new\s+THREE\b|THREE\.(?:WebGLRenderer|Scene|PerspectiveCamera|Vector3)\b|"
        r"['\"]https?://[^'\"]*three(?:\.min)?\.js|unpkg\.com/three|cdn\.jsdelivr\.net/(?:npm/)?three",
    ),
    (
        "gsap",
        r"(?:from|import)\s+['\"]gsap['\"]|gsap\.(?:to|timeline|registerPlugin|from)\b|"
        r"['\"]https?://[^'\"]*gsap|greensock",
    ),
    ("pixi", r"(?:from|import)\s+['\"]pixi\.js['\"]|@pixi/|\bPIXI\."),
    ("wgsl", r"\bwgsl\b|navigator\.gpu"),
    ("ogl", r"(?:from|import)\s+['\"]ogl['\"]|\bOGL\."),
    ("twgl", r"\btwgl\b|from\s+['\"]twgl"),
    ("regl", r"\bregl\b|require\(['\"]regl['\"]\)"),
    (GAUSSIAN_SPLAT_LIBRARY_PRIMARY, r"gaussian-splats-3d|GaussianSplats3D|gaussiansplats"),
)


def _sha8(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()[:8]


def _artifact_path(a: dict[str, Any]) -> str:
    return str(a.get("path") or a.get("file_path") or "").replace("\\", "/")


def _artifact_content(a: dict[str, Any]) -> str:
    c = a.get("content")
    return c if isinstance(c, str) else ""


def _artifact_role(a: dict[str, Any]) -> str:
    return str(a.get("role") or "").strip().lower()


def _concat_text(artifacts: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for a in artifacts:
        parts.append(_artifact_content(a))
    return "\n".join(parts)


def _detect_libraries_artifact(blob: str) -> list[str]:
    """Libraries with **artifact** evidence (imports, runtime API, CDN script URLs)."""
    low = blob.lower()
    out: list[str] = []
    for name, pat in _LIB_PATTERNS_ARTIFACT:
        if name in out:
            continue
        try:
            if re.search(pat, low, re.I):
                out.append(name)
        except re.error:
            continue
    return sorted(set(out))


def _detect_libraries(blob: str) -> list[str]:
    """Backward-compatible alias — strict artifact detection only."""
    return _detect_libraries_artifact(blob)


def _html_outline(html: str) -> dict[str, Any]:
    low = html.lower()
    tags = ("main", "header", "footer", "nav", "section", "article", "canvas", "video")
    present = [t for t in tags if f"<{t}" in low or f"<{t} " in low]
    title_m = re.search(r"<title[^>]*>([^<]{0,120})", html, re.I)
    h1_m = re.search(r"<h1[^>]*>([^<]{0,160})", html, re.I)
    return {
        "title_text": (title_m.group(1).strip() if title_m else "")[:120],
        "h1_text": (h1_m.group(1).strip() if h1_m else "")[:160],
        "landmark_tags": present[:12],
    }


def _interaction_cues(blob: str) -> list[str]:
    low = blob.lower()
    cues: list[str] = []
    for token, label in (
        ("addeventlistener", "js_events"),
        ("onclick", "inline_onclick"),
        ("<canvas", "canvas_element"),
        ("scroll", "scroll_driven"),
        ("requestanimationframe", "raf_loop"),
        ("webgl", "webgl"),
        ("three.", "three_api"),
    ):
        if token in low and label not in cues:
            cues.append(label)
    return cues[:10]


def _rendering_cues(blob: str, file_inventory: list[dict[str, Any]]) -> dict[str, Any]:
    low = blob.lower()
    paths = " ".join(f.get("path", "") for f in file_inventory).lower()
    return {
        "has_webgl_hint": "webgl" in low or "three." in low,
        "has_wgsl_files": any(str(f.get("type")) == "wgsl" for f in file_inventory),
        "has_glsl_files": any(str(f.get("type")) == "glsl" for f in file_inventory),
        "has_splat_assets": any(
            str(f.get("path", "")).lower().endswith((".splat", ".ply")) for f in file_inventory
        ),
        "shader_paths": [f["path"] for f in file_inventory if str(f.get("type")) in ("wgsl", "glsl", "vert", "frag")][
            :8
        ],
    }


def _diff_inventory(prev: list[dict[str, Any]], cur: list[dict[str, Any]]) -> dict[str, Any]:
    prev_paths = {str(x.get("path")) for x in prev if isinstance(x, dict)}
    cur_paths = {str(x.get("path")) for x in cur if isinstance(x, dict)}
    added = sorted(cur_paths - prev_paths)[:20]
    removed = sorted(prev_paths - cur_paths)[:20]
    return {"paths_added": added, "paths_removed": removed, "prev_file_count": len(prev_paths), "cur_file_count": len(cur_paths)}


def build_file_inventory(artifacts: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for a in artifacts:
        if not isinstance(a, dict):
            continue
        path = _artifact_path(a)
        if not path:
            continue
        content = _artifact_content(a)
        lang = str(a.get("language") or "").strip().lower()
        if not lang:
            lower = path.lower()
            for ext, typ in (
                (".html", "html"),
                (".htm", "html"),
                (".css", "css"),
                (".js", "js"),
                (".json", "json"),
                (".wgsl", "wgsl"),
                (".glsl", "glsl"),
                (".vert", "vert"),
                (".frag", "frag"),
                (".splat", "splat"),
                (".ply", "ply"),
            ):
                if lower.endswith(ext):
                    lang = typ
                    break
        rows.append(
            {
                "path": path,
                "role": _artifact_role(a) or None,
                "type": lang or "unknown",
                "size": len(content.encode("utf-8", errors="replace")),
                "digest8": _sha8(content) if content else None,
            }
        )
    rows.sort(key=lambda x: x["path"])
    return rows


def build_entrypoints(file_inventory: list[dict[str, Any]]) -> list[str]:
    ep: list[str] = []
    for row in file_inventory:
        p = str(row.get("path") or "").lower()
        if p.endswith(("index.html", "preview/index.html")) or "/preview/" in p and p.endswith(".html"):
            ep.append(row["path"])
    if not ep:
        for row in file_inventory:
            if str(row.get("type")) == "html":
                ep.append(row["path"])
                break
    return ep[:5]


def build_build_candidate_summary_v1(
    artifacts: list[Any],
    *,
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
    prior_summary: dict[str, Any] | None = None,
    generator_notes: str | None = None,
) -> dict[str, Any]:
    """
    Build a compact summary dict. ``artifacts`` should be normalized artifact dicts (with optional content).
    """
    arts = [a for a in artifacts if isinstance(a, dict)]
    inv = build_file_inventory(arts)
    blob = _concat_text(arts)
    libs = _detect_libraries_artifact(blob)
    ec = build_spec.get("execution_contract") if isinstance(build_spec.get("execution_contract"), dict) else {}
    esc = str(ec.get("escalation_lane") or "").strip().lower() or None
    allowed = ec.get("allowed_libraries") if isinstance(ec.get("allowed_libraries"), list) else []
    allowed_s = [str(x).strip().lower() for x in allowed if isinstance(x, str)]

    lane = "static"
    if is_interactive_frontend_vertical(build_spec, event_input):
        lane = "interactive_frontend_app_v1"

    entry = build_entrypoints(inv)
    outline: dict[str, Any] = {}
    for a in arts:
        p = _artifact_path(a).lower()
        if p.endswith((".html", ".htm")):
            outline = _html_outline(_artifact_content(a))
            break

    warnings: list[str] = []
    if lane == "interactive_frontend_app_v1" and esc == "gaussian_splat_v1":
        if not any(str(r.get("path", "")).lower().endswith((".splat", ".ply")) for r in inv):
            warnings.append("gaussian_splat_lane_active_but_no_splat_ply_asset_in_bundle")

    compliance_summary: dict[str, Any] = {
        "escalation_lane": esc,
        "allowed_libraries_contract": allowed_s[:12],
        "libraries_detected_in_artifacts": libs,
        "libraries_expected_from_execution_contract": allowed_s[:12],
        "library_detection_provenance": "artifact_source_code",
    }

    # Required-library compliance: explicit pass/fail surface for evaluator and operator.
    req_raw = ec.get("required_libraries") if isinstance(ec.get("required_libraries"), list) else []
    req_s = sorted({str(x).strip().lower() for x in req_raw if isinstance(x, str) and x.strip()})
    req_missing = [r for r in req_s if r not in libs]
    required_libraries_compliance: dict[str, Any] = {
        "required": req_s,
        "detected": libs,
        "missing": req_missing,
        "satisfied": len(req_missing) == 0,
    }

    prev_iter: dict[str, Any] | None = None
    if isinstance(prior_summary, dict) and prior_summary.get("file_inventory"):
        prev_inv = prior_summary.get("file_inventory")
        if isinstance(prev_inv, list):
            prev_iter = _diff_inventory(prev_inv, inv)

    out: dict[str, Any] = {
        "summary_version": SUMMARY_VERSION,
        "lane": lane,
        "escalation_lane": esc,
        "libraries_detected": libs,
        "library_detection": {
            "libraries_detected_artifact": libs,
            "libraries_expected_from_execution_contract": allowed_s[:12],
            "libraries_runtime": None,
            "provenance_artifact": "artifact_source_code",
            "provenance_contract": "build_spec.execution_contract.allowed_libraries",
        },
        "file_inventory": inv[:40],
        "file_inventory_truncated": len(inv) > 40,
        "entrypoints": entry,
        "experience_summary": {
            "experience_mode": (build_spec.get("experience_mode") if isinstance(build_spec.get("experience_mode"), str) else None),
            "surface_type": ec.get("surface_type"),
            "artifact_count": len(arts),
        },
        "sections_or_modules": outline,
        "interaction_summary": {"cues": _interaction_cues(blob)},
        "rendering_summary": _rendering_cues(blob, inv),
        "asset_summary": {
            "splat_or_ply": sum(
                1 for r in inv if str(r.get("path", "")).lower().endswith((".splat", ".ply"))
            ),
            "image_like_paths": sum(
                1
                for r in inv
                if str(r.get("path", "")).lower().endswith(
                    (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")
                )
            ),
        },
        "compliance_summary": compliance_summary,
        "required_libraries_compliance": required_libraries_compliance,
        "warnings": warnings[:8],
        "previous_iteration_diff_summary": prev_iter,
    }
    if generator_notes and isinstance(generator_notes, str) and generator_notes.strip():
        out["generator_notes_orchestrator_unverified"] = generator_notes.strip()[:400]
    return out


def strip_artifact_contents(artifacts: list[Any]) -> list[dict[str, Any]]:
    """Replace file contents with metadata only (for graph state / slim payloads)."""
    slim: list[dict[str, Any]] = []
    for a in artifacts:
        if not isinstance(a, dict):
            continue
        path = _artifact_path(a)
        content = _artifact_content(a)
        row = {k: v for k, v in a.items() if k != "content"}
        row["content_omitted"] = True
        row["content_len"] = len(content.encode("utf-8", errors="replace"))
        if content:
            row["digest8"] = _sha8(content)
        if path:
            row["path"] = path
        slim.append(row)
    return slim


def build_slim_build_candidate_state_dict(
    *,
    raw_generator: dict[str, Any],
    summary: dict[str, Any],
    snippets: dict[str, Any] | None,
    full_artifacts: list[Any],
    summary_v2: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Graph-state / evaluator-payload-friendly build_candidate without full artifact bodies.

    Preview URL and sandbox_ref are preserved for routing; deterministic gates load full refs from DB.
    """
    slim_arts = strip_artifact_contents(full_artifacts)
    out: dict[str, Any] = {
        "proposed_changes": raw_generator.get("proposed_changes"),
        "artifact_outputs": slim_arts,
        "updated_state": raw_generator.get("updated_state"),
        "sandbox_ref": raw_generator.get("sandbox_ref"),
        "preview_url": raw_generator.get("preview_url"),
        "block_anchors": raw_generator.get("block_anchors"),
        "execution_acknowledgment": raw_generator.get("execution_acknowledgment"),
        "_kmbl_compliance": raw_generator.get("_kmbl_compliance"),
        "kmbl_build_candidate_summary_v1": summary,
    }
    if summary_v2 is not None:
        out["kmbl_build_candidate_summary_v2"] = summary_v2
    if snippets:
        out["kmbl_evaluator_artifact_snippets_v1"] = snippets
    return out


def merge_summary_into_raw_payload(
    raw_payload: dict[str, Any] | None,
    summary: dict[str, Any],
    summary_v2: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = dict(raw_payload or {})
    base["kmbl_build_candidate_summary_v1"] = summary
    if summary_v2 is not None:
        base["kmbl_build_candidate_summary_v2"] = summary_v2
    return base


def build_candidate_dict_from_artifact_refs(refs: list[Any] | None) -> dict[str, Any]:
    """Rebuild {artifact_outputs: [...]} with full content for deterministic evaluator gates."""
    if not refs:
        return {"artifact_outputs": []}
    return {"artifact_outputs": [dict(x) for x in refs if isinstance(x, dict)]}


def merge_slim_with_full_artifacts_for_gates(
    slim: dict[str, Any],
    full_refs: list[Any] | None,
) -> dict[str, Any]:
    """
    Evaluator deterministic gates need full ``content`` bodies.

    When graph state carries slim ``artifact_outputs`` (``content_omitted``), substitute rows
    from persisted ``artifact_refs_json``. Legacy state with full bodies is unchanged.
    """
    out = dict(slim)
    slim_ao = slim.get("artifact_outputs") if isinstance(slim.get("artifact_outputs"), list) else []
    use_full = False
    if not slim_ao:
        use_full = True
    else:
        first = slim_ao[0]
        if isinstance(first, dict) and first.get("content_omitted"):
            use_full = True
    if use_full and full_refs:
        out["artifact_outputs"] = [dict(x) for x in full_refs if isinstance(x, dict)]
    return out


def summary_json_size(summary: dict[str, Any]) -> int:
    try:
        return len(json.dumps(summary, ensure_ascii=False, default=str))
    except Exception:
        return -1


def build_lean_summary_for_payload(summary: dict[str, Any]) -> dict[str, Any]:
    """Return a minimal view of the summary for token-sensitive payloads.

    Keeps:
    - ``entrypoints``
    - ``file_inventory`` (paths + roles, no content)
    - ``required_libraries_compliance``
    - ``lane``, ``escalation_lane``
    - ``experience_summary``

    Drops heavy sub-dicts like ``interaction_summary``, ``rendering_summary``,
    ``sections_or_modules``, ``compliance_summary`` (redundant with
    ``required_libraries_compliance``), ``previous_iteration_diff_summary``.
    """
    if not isinstance(summary, dict):
        return {}
    _LEAN_KEYS = {
        "summary_version",
        "lane",
        "escalation_lane",
        "libraries_detected",
        "file_inventory",
        "file_inventory_truncated",
        "entrypoints",
        "experience_summary",
        "required_libraries_compliance",
        "warnings",
    }
    return {k: v for k, v in summary.items() if k in _LEAN_KEYS}
