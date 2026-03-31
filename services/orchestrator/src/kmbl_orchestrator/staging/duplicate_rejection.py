"""Detect duplicate static outputs vs prior staging snapshots on the same thread."""

from __future__ import annotations

import hashlib
import re
from typing import Any
from uuid import UUID

from kmbl_orchestrator.domain import BuildCandidateRecord, EvaluationReportRecord
from kmbl_orchestrator.persistence.repository import Repository


def _normalize_code(text: str) -> str:
    """Collapse whitespace so trivial formatting diffs do not mask duplicates."""
    t = text.strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def fingerprint_static_artifacts(
    artifact_refs: list[Any],
    working_state_patch: dict[str, Any],
) -> str | None:
    """
    Stable fingerprint from static_frontend_file_v1 rows (path + language + content).

    Returns None when there are no static file artifacts to compare.
    """
    rows = [
        a
        for a in artifact_refs
        if isinstance(a, dict) and a.get("role") == "static_frontend_file_v1"
    ]
    if not rows:
        return None
    parts: list[str] = []
    for a in sorted(rows, key=lambda r: str(r.get("path", ""))):
        path = str(a.get("path", ""))
        lang = str(a.get("language", ""))
        raw = a.get("content")
        c = str(raw) if raw is not None else ""
        parts.append(f"{path}|{lang}|{_normalize_code(c)}")
    blob = "\n".join(parts)
    # Include preview entry hint so same files with different preview selection differ
    pv = working_state_patch.get("static_frontend_preview_v1")
    if isinstance(pv, dict):
        ep = pv.get("entry_path")
        if isinstance(ep, str) and ep.strip():
            blob += f"\npreview_entry:{ep.strip()}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fingerprint_from_snapshot_payload(payload: dict[str, Any]) -> str | None:
    arts: list[Any] = []
    wsp: dict[str, Any] = {}
    art_block = payload.get("artifacts")
    if isinstance(art_block, dict):
        ar = art_block.get("artifact_refs")
        if isinstance(ar, list):
            arts = ar
    meta = payload.get("metadata")
    if isinstance(meta, dict):
        wp = meta.get("working_state_patch")
        if isinstance(wp, dict):
            wsp = wp
    return fingerprint_static_artifacts(arts, wsp)


def fingerprint_build_candidate(bc: BuildCandidateRecord) -> str | None:
    return fingerprint_static_artifacts(
        list(bc.artifact_refs_json),
        dict(bc.working_state_patch_json),
    )


def apply_duplicate_staging_rejection(
    report: EvaluationReportRecord,
    *,
    bc: BuildCandidateRecord,
    repo: Repository,
    thread_id: UUID,
    graph_run_id: UUID,
) -> EvaluationReportRecord:
    """
    If the build matches a prior staging snapshot's static fingerprint, force fail.

    Downgrades pass/partial so the graph iterates instead of recording duplicate review rows.
    """
    if report.status == "blocked":
        return report
    fp = fingerprint_build_candidate(bc)
    if fp is None:
        return report

    prior = repo.list_staging_snapshots_for_thread(thread_id, limit=50)
    for snap in prior:
        if snap.graph_run_id == graph_run_id:
            continue
        p = snap.snapshot_payload_json
        if not isinstance(p, dict):
            continue
        fp_old = fingerprint_from_snapshot_payload(p)
        if fp_old is None or fp_old != fp:
            continue
        if report.status not in ("pass", "partial"):
            return report
        new_metrics = dict(report.metrics_json)
        new_metrics["duplicate_rejection"] = True
        new_metrics["duplicate_of_staging_snapshot_id"] = str(snap.staging_snapshot_id)
        issues = list(report.issues_json)
        issues.append(
            {
                "code": "duplicate_output",
                "message": (
                    "Build matches a previous staging snapshot (same static files). "
                    "Iterate with a meaningfully different layout or content."
                ),
            }
        )
        summary = (report.summary or "").strip()
        suffix = "[Rejected as duplicate of prior staging]"
        if suffix not in summary:
            summary = f"{summary} {suffix}".strip() if summary else suffix
        return report.model_copy(
            update={
                "status": "fail",
                "summary": summary,
                "issues_json": issues,
                "metrics_json": new_metrics,
            }
        )
    return report
