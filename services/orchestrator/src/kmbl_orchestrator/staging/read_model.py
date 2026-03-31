"""Derived read-model fields for staging (Pass C) — only ``snapshot_payload_json`` + row columns.

Proposals and list rows are **read models** for operator review — not workflow state machines.
"""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.runtime.scenario_visibility import (
    gallery_strip_visibility_from_staging_payload,
    static_frontend_visibility_from_staging_payload,
)

from kmbl_orchestrator.domain import (
    PublicationSnapshotRecord,
    StagingSnapshotRecord,
    WorkingStagingRecord,
)


def review_readiness_for_staging_record(rec: StagingSnapshotRecord) -> dict[str, Any]:
    return {
        "ready": rec.status == "review_ready",
        "approved": rec.status == "approved",
        "rejected": rec.status == "rejected",
        "basis": "persisted_snapshot",
        "staging_status": rec.status,
    }


def evaluation_summary_from_payload(payload: dict[str, Any]) -> str:
    """V1 payload: ``evaluation.summary``."""
    ev = payload.get("evaluation")
    if isinstance(ev, dict):
        s = ev.get("summary")
        if isinstance(s, str):
            return s
    return ""


def short_title_from_payload(payload: dict[str, Any]) -> str | None:
    """V1 payload: ``summary.title`` (build_spec title slice)."""
    summ = payload.get("summary")
    if isinstance(summ, dict):
        t = summ.get("title")
        if isinstance(t, str) and t.strip():
            return t.strip()[:200]
    return None


def payload_version_from_payload(payload: dict[str, Any]) -> int | None:
    v = payload.get("version")
    return v if isinstance(v, int) else None


def compact_title_from_payload(
    payload: dict[str, Any], *, staging_snapshot_id: str
) -> str:
    """Card title: ``summary.title``, optional ``build_spec.title``, then a stable fallback label."""
    st = short_title_from_payload(payload)
    if st:
        return st
    bs = payload.get("build_spec")
    if isinstance(bs, dict):
        t = bs.get("title")
        if isinstance(t, str) and t.strip():
            return t.strip()[:200]
    s = staging_snapshot_id.replace("-", "")
    if len(s) >= 8:
        return f"Staging snapshot {s[:8]}…"
    return f"Staging snapshot {staging_snapshot_id}"


def identity_hint_from_uuid(identity_id: Any) -> str | None:
    """Short display hint when an identity UUID is present."""
    if identity_id is None:
        return None
    s = str(identity_id).replace("-", "")
    return (s[:8] + "…") if len(s) >= 8 else str(identity_id)


def staging_snapshot_list_item(rec: StagingSnapshotRecord) -> dict[str, Any]:
    """Lightweight row for GET /orchestrator/staging (no full ``snapshot_payload_json``)."""
    p = dict(rec.snapshot_payload_json)
    sid = str(rec.staging_snapshot_id)
    ev_sum = evaluation_summary_from_payload(p)
    title = compact_title_from_payload(p, staging_snapshot_id=sid)
    ih = identity_hint_from_uuid(rec.identity_id)
    gv = gallery_strip_visibility_from_staging_payload(p)
    fv = static_frontend_visibility_from_staging_payload(p)
    has_g = bool(gv.get("has_gallery_strip"))
    has_f = bool(fv.get("has_static_frontend"))
    if has_g and has_f:
        ck = "mixed"
    elif has_g:
        ck = "gallery_strip"
    elif has_f:
        ck = "static_frontend"
    else:
        ck = None
    out: dict[str, Any] = {
        "staging_snapshot_id": sid,
        "thread_id": str(rec.thread_id),
        "identity_id": str(rec.identity_id) if rec.identity_id else None,
        "status": rec.status,
        "created_at": rec.created_at,
        "preview_url": rec.preview_url,
        "evaluation_summary": ev_sum,
        "review_readiness": review_readiness_for_staging_record(rec),
        "title": title,
        "payload_version": payload_version_from_payload(p),
        "content_kind": ck,
        "has_gallery_strip": has_g,
        "has_static_frontend": has_f,
        "static_frontend_file_count": int(fv.get("static_frontend_file_count") or 0),
        "static_frontend_bundle_count": int(fv.get("static_frontend_bundle_count") or 0),
        "has_previewable_html": bool(fv.get("has_previewable_html")),
    }
    if ih:
        out["identity_hint"] = ih
    return out


def proposal_read_model(rec: StagingSnapshotRecord) -> dict[str, Any]:
    """Thin read-only proposal row — ``proposal_id`` aliases ``staging_snapshot_id`` for now."""
    p = dict(rec.snapshot_payload_json)
    sid = str(rec.staging_snapshot_id)
    ev_sum = evaluation_summary_from_payload(p)
    title = compact_title_from_payload(p, staging_snapshot_id=sid)
    rr = review_readiness_for_staging_record(rec)
    gv = gallery_strip_visibility_from_staging_payload(p)
    fv = static_frontend_visibility_from_staging_payload(p)
    has_g = bool(gv.get("has_gallery_strip"))
    has_f = bool(fv.get("has_static_frontend"))
    if has_g and has_f:
        content_kind = "mixed"
    elif has_g:
        content_kind = "gallery_strip"
    elif has_f:
        content_kind = "static_frontend"
    else:
        content_kind = None
    out: dict[str, Any] = {
        "proposal_id": sid,
        "staging_snapshot_id": sid,
        "thread_id": str(rec.thread_id),
        "identity_id": str(rec.identity_id) if rec.identity_id else None,
        "preview_url": rec.preview_url,
        "title": title,
        "summary": title,
        "evaluation_summary": ev_sum,
        "created_at": rec.created_at,
        "review_readiness": rr,
        "staging_status": rec.status,
        "approved_at": rec.approved_at,
        "approved_by": rec.approved_by,
        "content_kind": content_kind,
        "has_gallery_strip": gv.get("has_gallery_strip", False),
        "gallery_strip_item_count": gv.get("gallery_strip_item_count", 0),
        "gallery_image_artifact_count": gv.get("gallery_image_artifact_count", 0),
        "gallery_items_with_artifact_key": gv.get("gallery_items_with_artifact_key", 0),
        "has_static_frontend": has_f,
        "static_frontend_file_count": int(fv.get("static_frontend_file_count") or 0),
        "static_frontend_bundle_count": int(fv.get("static_frontend_bundle_count") or 0),
        "has_previewable_html": bool(fv.get("has_previewable_html")),
    }
    return out


def linked_publications_read_model(
    publications: list[PublicationSnapshotRecord],
) -> list[dict[str, Any]]:
    """Newest ``published_at`` first — for staging detail (Pass F)."""
    rows = sorted(publications, key=lambda p: p.published_at, reverse=True)
    return [
        {
            "publication_snapshot_id": str(p.publication_snapshot_id),
            "published_at": p.published_at,
            "published_by": p.published_by,
            "visibility": p.visibility,
        }
        for p in rows
    ]


def staging_lineage_read_model(
    rec: StagingSnapshotRecord, payload: dict[str, Any]
) -> dict[str, Any]:
    """
    Provenance ids for operator lineage (Pass G) — row columns + ``payload.ids`` only.
    """
    ids = payload.get("ids")
    eval_id: str | None = None
    prior_from_payload: str | None = None
    if isinstance(ids, dict):
        er = ids.get("evaluation_report_id")
        if er is not None:
            eval_id = str(er)
        ps = ids.get("prior_staging_snapshot_id")
        if ps is not None:
            prior_from_payload = str(ps)
    prior_s: str | None = (
        str(rec.prior_staging_snapshot_id)
        if rec.prior_staging_snapshot_id is not None
        else prior_from_payload
    )
    return {
        "thread_id": str(rec.thread_id),
        "graph_run_id": str(rec.graph_run_id) if rec.graph_run_id else None,
        "build_candidate_id": str(rec.build_candidate_id),
        "evaluation_report_id": eval_id,
        "identity_id": str(rec.identity_id) if rec.identity_id else None,
        "prior_staging_snapshot_id": prior_s,
    }


def evaluation_summary_section_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Thin evaluation read model from persisted snapshot payload (Pass G)."""
    ev = payload.get("evaluation")
    if not isinstance(ev, dict):
        return {
            "present": False,
            "status": None,
            "summary": "",
            "issue_count": 0,
            "artifact_count": 0,
            "metrics_key_count": 0,
            "metrics_preview": {},
        }
    issues = ev.get("issues")
    issue_count = len(issues) if isinstance(issues, list) else 0
    metrics = ev.get("metrics")
    metrics_key_count = 0
    metrics_preview: dict[str, Any] = {}
    if isinstance(metrics, dict):
        metrics_key_count = len(metrics)
        for i, (k, v) in enumerate(metrics.items()):
            if i >= 5:
                break
            key = str(k)
            if isinstance(v, (str, int, float, bool)) or v is None:
                s = repr(v) if v is not None else "null"
            else:
                s = str(v)
            if len(s) > 80:
                s = s[:77] + "..."
            metrics_preview[key] = s
    arts = payload.get("artifacts")
    artifact_count = 0
    if isinstance(arts, dict):
        ar = arts.get("artifact_refs")
        artifact_count = len(ar) if isinstance(ar, list) else 0
    summary = ev.get("summary")
    sum_s = summary if isinstance(summary, str) else ""
    st = ev.get("status")
    status_s = str(st) if isinstance(st, str) else None
    return {
        "present": True,
        "status": status_s,
        "summary": sum_s,
        "issue_count": issue_count,
        "artifact_count": artifact_count,
        "metrics_key_count": metrics_key_count,
        "metrics_preview": metrics_preview,
    }


def review_readiness_explanation_for_staging(
    rec: StagingSnapshotRecord,
    payload: dict[str, Any],
) -> str:
    """
    Human-readable explanation from persisted staging status + payload only (Pass G).

    Does not infer runtime or checkpoint state.
    """
    ev = payload.get("evaluation")
    ev_status: str | None = None
    if isinstance(ev, dict):
        s = ev.get("status")
        ev_status = str(s) if isinstance(s, str) else None
    st = rec.status

    if st == "rejected":
        return (
            "Staging is rejected — this snapshot is closed for approval and publication. "
            "Start a new staging snapshot from the graph if you need another review cycle."
        )

    if st == "review_ready":
        if not isinstance(ev, dict):
            return (
                "Persisted snapshot payload has no evaluation section — evaluator output "
                "cannot be verified from stored data; treat as not ready for confident review."
            )
        if ev_status is None:
            return (
                "Persisted evaluation has no status field — review readiness cannot be "
                "confirmed from stored data alone."
            )
        if ev_status == "pass":
            return (
                "Staging status is review_ready and persisted evaluation status is pass — "
                "eligible for operator review in the default workflow."
            )
        return (
            f"Staging is review_ready but persisted evaluation status is {ev_status!r}. "
            "Confirm policy before approving."
        )

    if st == "approved":
        return (
            "Staging is approved — you may publish once to canon if no publication "
            "snapshot exists yet for this staging id (see duplicate-publication policy)."
        )

    return (
        f"Staging status is {st!r}. Use review_readiness flags and the persisted snapshot "
        "payload to assess next steps."
    )


def staging_lifecycle_timeline(
    rec: StagingSnapshotRecord,
    publications: list[PublicationSnapshotRecord],
) -> list[dict[str, Any]]:
    """
    Minimal lifecycle from persisted rows only (Pass F).

    Omits events when a timestamp cannot be proven (e.g. approval without ``approved_at``).
    """
    out: list[dict[str, Any]] = []
    out.append(
        {
            "kind": "staging_persisted",
            "label": "Staging snapshot recorded (review surface)",
            "at": rec.created_at,
            "ref_publication_snapshot_id": None,
        }
    )
    if rec.status in ("review_ready", "approved"):
        out.append(
            {
                "kind": "review_ready",
                "label": "Eligible for operator review (review-ready)",
                "at": rec.created_at,
                "ref_publication_snapshot_id": None,
            }
        )
    if rec.status == "approved" and rec.approved_at:
        out.append(
            {
                "kind": "approved",
                "label": "Operator approval recorded (staging)",
                "at": rec.approved_at,
                "ref_publication_snapshot_id": None,
            }
        )
    if rec.status == "rejected" and rec.rejected_at:
        out.append(
            {
                "kind": "rejected",
                "label": "Operator rejection recorded (staging)",
                "at": rec.rejected_at,
                "ref_publication_snapshot_id": None,
            }
        )
    pubs_sorted = sorted(publications, key=lambda p: p.published_at)
    for pub in pubs_sorted:
        out.append(
            {
                "kind": "published",
                "label": "Publication snapshot created (immutable canon)",
                "at": pub.published_at,
                "ref_publication_snapshot_id": str(pub.publication_snapshot_id),
            }
        )
    return out


# --- Working staging read model ---


def working_staging_read_model(ws: WorkingStagingRecord) -> dict[str, Any]:
    """Compact read model for the mutable working staging surface."""
    p = dict(ws.payload_json)
    fv = static_frontend_visibility_from_staging_payload(p)
    gv = gallery_strip_visibility_from_staging_payload(p)
    has_f = bool(fv.get("has_static_frontend"))
    has_g = bool(gv.get("has_gallery_strip"))

    if has_g and has_f:
        content_kind = "mixed"
    elif has_g:
        content_kind = "gallery_strip"
    elif has_f:
        content_kind = "static_frontend"
    else:
        content_kind = None

    title = short_title_from_payload(p)
    ev_sum = evaluation_summary_from_payload(p)

    patches_since_rebuild = 0
    if ws.last_rebuild_revision is not None:
        patches_since_rebuild = max(0, ws.revision - ws.last_rebuild_revision)
    elif ws.revision > 0:
        patches_since_rebuild = ws.revision

    revision_summary = ws.last_revision_summary_json if ws.last_revision_summary_json else None

    return {
        "working_staging_id": str(ws.working_staging_id),
        "thread_id": str(ws.thread_id),
        "identity_id": str(ws.identity_id) if ws.identity_id else None,
        "revision": ws.revision,
        "status": ws.status,
        "last_update_mode": ws.last_update_mode,
        "created_at": ws.created_at,
        "updated_at": ws.updated_at,
        "title": title,
        "evaluation_summary": ev_sum,
        "content_kind": content_kind,
        "has_static_frontend": has_f,
        "has_previewable_html": bool(fv.get("has_previewable_html")),
        "static_frontend_file_count": int(fv.get("static_frontend_file_count") or 0),
        "has_gallery_strip": has_g,
        "identity_hint": identity_hint_from_uuid(ws.identity_id),
        "patches_since_rebuild": patches_since_rebuild,
        "stagnation_count": ws.stagnation_count,
        "last_rebuild_revision": ws.last_rebuild_revision,
        "last_revision_summary": revision_summary,
    }
