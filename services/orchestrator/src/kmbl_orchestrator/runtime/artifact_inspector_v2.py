"""
Orchestrator-owned artifact inspection summary (v2) — canonical, deterministic, not model self-report.

Built from persisted/normalized artifact dicts (and optional generator wire metadata such as
``workspace_manifest_v1``). Downstream model payloads should prefer this + preview over raw code echo.
"""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.runtime.build_candidate_summary_v1 import build_build_candidate_summary_v1


def _manifest_paths(generator_raw: dict[str, Any] | None) -> list[str]:
    if not isinstance(generator_raw, dict):
        return []
    wm = generator_raw.get("workspace_manifest_v1")
    if not isinstance(wm, dict):
        return []
    files = wm.get("files")
    if not isinstance(files, list):
        return []
    paths: list[str] = []
    for f in files:
        if not isinstance(f, dict):
            continue
        p = f.get("path")
        if isinstance(p, str) and p.strip():
            paths.append(p.strip().replace("\\", "/"))
    return sorted(set(paths))[:48]


def build_build_candidate_summary_v2(
    artifacts: list[Any],
    *,
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
    prior_summary: dict[str, Any] | None = None,
    generator_notes: str | None = None,
    generator_raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Deterministic v2 summary: starts from v1 inspection, adds artifact-first / review-input fields.

    ``prior_summary`` may be v1 or v2 (must carry ``file_inventory`` for diff fields in v1 base).
    """
    v1 = build_build_candidate_summary_v1(
        artifacts,
        build_spec=build_spec,
        event_input=event_input,
        prior_summary=prior_summary,
        generator_notes=generator_notes,
    )
    manifest_paths = _manifest_paths(generator_raw)
    entry = v1.get("entrypoints") if isinstance(v1.get("entrypoints"), list) else []
    exp = v1.get("experience_summary") if isinstance(v1.get("experience_summary"), dict) else {}
    ac = int(exp.get("artifact_count") or 0)
    warns = v1.get("warnings") if isinstance(v1.get("warnings"), list) else []

    preview_ok = bool(entry) and ac > 0
    build_complete_hint = preview_ok and len(warns) == 0

    v2: dict[str, Any] = dict(v1)
    v2["summary_version"] = 2
    v2["canonical_source"] = "orchestrator_artifact_inspection_v2"
    v2["artifact_first"] = {
        "slim_model_payload_default": True,
        "full_file_bodies_in_workspace_or_db_only": True,
        "generator_manifest_paths": manifest_paths,
        "generator_self_summary_is_unverified": bool(generator_notes and str(generator_notes).strip()),
    }
    v2["preview_readiness"] = {
        "has_resolved_entrypoints": preview_ok,
        "notes": []
        if preview_ok
        else ["no_entrypoints_or_empty_artifact_set"],
    }
    v2["review_eligibility_inputs"] = {
        "build_appears_sufficient_for_preview": build_complete_hint,
        "blocking_warnings_count": len(warns),
        "notes": []
        if build_complete_hint
        else ["warnings_present_or_missing_entrypoint"],
    }
    return v2
