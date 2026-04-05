"""Deterministic staging_snapshot payload from persisted rows only."""

from __future__ import annotations

import logging
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from kmbl_orchestrator.contracts.frontend_artifact_roles import is_frontend_file_artifact_role
from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    BuildSpecRecord,
    EvaluationReportRecord,
    ThreadRecord,
)

_log = logging.getLogger(__name__)

# --- Explicit v1 contract (stable for review consumers; no raw provider blobs) ---


class StagingPayloadIdsV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    graph_run_id: str
    build_candidate_id: str
    evaluation_report_id: str
    identity_id: str | None = None
    build_spec_id: str | None = None
    prior_staging_snapshot_id: str | None = None


class StagingPayloadSummaryV1(BaseModel):
    """High-level build_spec summary (from persisted spec_json only)."""

    model_config = ConfigDict(extra="forbid")

    type: str | None = None
    title: str | None = None


class StagingPayloadEvaluationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    summary: str = ""
    issues: list[Any] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class StagingPayloadPreviewV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_url: str | None = None
    sandbox_ref: str | None = None


class StagingPayloadArtifactsV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_refs: list[Any] = Field(default_factory=list)


class StagingPayloadFrontendStaticFileV1(BaseModel):
    """One normalized static file row (mirrors persisted ``static_frontend_file_v1``)."""

    model_config = ConfigDict(extra="forbid")

    path: str
    language: Literal["html", "css", "js", "json", "glsl", "wgsl"]
    bundle_id: str | None = None
    previewable: bool
    entry_for_preview: bool


class StagingPayloadFrontendStaticBundleV1(BaseModel):
    """Files grouped by ``bundle_id`` (``null`` = ungrouped)."""

    model_config = ConfigDict(extra="forbid")

    bundle_id: str | None = None
    file_paths: list[str] = Field(default_factory=list)
    preview_entry_path: str | None = None


class StagingPayloadFrontendStaticV1(BaseModel):
    """
    Derived review hints for simple HTML/CSS/JS artifacts (no sandbox; additive to v1).

    ``convention`` documents the path prefix rule for generator emitters.
    """

    model_config = ConfigDict(extra="forbid")

    convention: Literal["component_paths_v1"] = "component_paths_v1"
    file_count: int = 0
    bundle_count: int = 0
    has_previewable_html: bool = False
    files: list[StagingPayloadFrontendStaticFileV1] = Field(default_factory=list)
    bundles: list[StagingPayloadFrontendStaticBundleV1] = Field(default_factory=list)
    patch_preview_entry_path: str | None = None


class StagingPayloadHabitatPageV1(BaseModel):
    """Habitat page summary for review UIs."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    title: str
    section_count: int = 0
    file_path: str | None = None


class StagingPayloadHabitatV1(BaseModel):
    """
    Derived review hints for habitat-assembled artifacts.

    Provides summary information about the habitat structure for review UIs.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    slug: str
    framework: str
    theme: str
    page_count: int = 0
    file_count: int = 0
    pages: list[StagingPayloadHabitatPageV1] = Field(default_factory=list)
    libraries: list[str] = Field(default_factory=list)
    has_custom_css: bool = False
    has_custom_js: bool = False


class StagingPayloadMetadataV1(BaseModel):
    """Non-UI working state slice persisted on the candidate (no raw KiloClaw envelope)."""

    model_config = ConfigDict(extra="forbid")

    working_state_patch: dict[str, Any] = Field(default_factory=dict)
    frontend_static: StagingPayloadFrontendStaticV1 | None = None
    habitat: StagingPayloadHabitatV1 | None = None
    preview_kind: Literal["static", "external_url"] = Field(
        default="static",
        description="static: assembled preview from artifacts; external_url: primary surface is a hosted URL.",
    )
    content_reuse_note: str | None = Field(
        default=None,
        description="When prior staging exists: generated images / gallery URLs may repeat as content.",
    )
    # Preview anchors derived from html_block_v1 amendments.
    # The first entry is the primary anchor to append to the staging preview URL.
    block_preview_anchors: list[str] = Field(default_factory=list)


class StagingSnapshotPayloadV1(BaseModel):
    """
    Versioned snapshot body stored in ``staging_snapshot.snapshot_payload_json``.

    Sections: ``ids``, ``summary``, ``evaluation``, ``preview``, ``artifacts``, ``metadata``.
    Built only from repository rows — no runtime-only fields.
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    ids: StagingPayloadIdsV1
    summary: StagingPayloadSummaryV1
    evaluation: StagingPayloadEvaluationV1
    preview: StagingPayloadPreviewV1
    artifacts: StagingPayloadArtifactsV1
    metadata: StagingPayloadMetadataV1


def derive_frontend_static_v1(
    artifact_refs: list[Any],
    working_state_patch: dict[str, Any],
) -> StagingPayloadFrontendStaticV1 | None:
    """
    Build a deterministic summary of static / interactive frontend file artifacts for review UIs.

    ``preview_entry_path`` per bundle: explicit ``entry_for_preview``, else
    ``static_frontend_preview_v1.entry_path`` when it matches that bundle, else first
    previewable HTML path in the bundle (sorted by ``path``).
    """
    static_rows: list[dict[str, Any]] = []
    for a in artifact_refs:
        if isinstance(a, dict) and is_frontend_file_artifact_role(a.get("role")):
            static_rows.append(a)

    if not static_rows:
        return None

    patch_preview: str | None = None
    raw_pv = working_state_patch.get("static_frontend_preview_v1")
    if isinstance(raw_pv, dict):
        ep = raw_pv.get("entry_path")
        if isinstance(ep, str) and ep.strip():
            patch_preview = ep.strip().replace("\\", "/")

    files_out: list[StagingPayloadFrontendStaticFileV1] = []
    for row in sorted(static_rows, key=lambda r: str(r.get("path", ""))):
        path = str(row["path"])
        lang = row.get("language")
        if lang not in ("html", "css", "js", "json", "glsl", "wgsl"):
            _log.warning("derive_frontend_static_v1: skipping artifact with unknown language=%s path=%s", lang, path)
            continue
        bid = row.get("bundle_id")
        bkey = bid if isinstance(bid, str) else None
        pv = row.get("previewable")
        previewable = bool(pv) if pv is not None else (lang == "html")
        ef = bool(row.get("entry_for_preview"))
        files_out.append(
            StagingPayloadFrontendStaticFileV1(
                path=path,
                language=lang,
                bundle_id=bkey,
                previewable=previewable,
                entry_for_preview=ef,
            )
        )

    has_html = any(f.language == "html" and f.previewable for f in files_out)
    by_bundle: dict[str | None, list[StagingPayloadFrontendStaticFileV1]] = {}
    for f in files_out:
        by_bundle.setdefault(f.bundle_id, []).append(f)

    bundles_out: list[StagingPayloadFrontendStaticBundleV1] = []
    for bkey in sorted(by_bundle.keys(), key=lambda k: (k is None, k or "")):
        group = sorted(by_bundle[bkey], key=lambda x: x.path)
        paths = [g.path for g in group]
        entry: str | None = None
        for g in group:
            if g.entry_for_preview and g.language == "html":
                entry = g.path
                break
        if entry is None and patch_preview and patch_preview in paths:
            entry = patch_preview
        if entry is None:
            for g in group:
                if g.language == "html" and g.previewable:
                    entry = g.path
                    break
        bundles_out.append(
            StagingPayloadFrontendStaticBundleV1(
                bundle_id=bkey,
                file_paths=paths,
                preview_entry_path=entry,
            )
        )

    return StagingPayloadFrontendStaticV1(
        file_count=len(files_out),
        bundle_count=len(bundles_out),
        has_previewable_html=has_html,
        files=files_out,
        bundles=bundles_out,
        patch_preview_entry_path=patch_preview,
    )


def derive_habitat_v1(
    artifact_refs: list[Any],
    working_state_patch: dict[str, Any],
) -> StagingPayloadHabitatV1 | None:
    """
    Build a deterministic summary of habitat artifacts for review UIs.

    Extracts habitat metadata from the working state patch if present,
    or infers it from bundle structure.
    """
    habitat_meta = working_state_patch.get("habitat_manifest_v2")
    if not isinstance(habitat_meta, dict):
        static_rows = [
            a for a in artifact_refs
            if isinstance(a, dict) and is_frontend_file_artifact_role(a.get("role"))
        ]
        if not static_rows:
            return None

        bundles: set[str] = set()
        for row in static_rows:
            bid = row.get("bundle_id")
            if isinstance(bid, str) and bid:
                bundles.add(bid)

        if len(bundles) != 1:
            return None

        bundle_slug = list(bundles)[0]
        html_files = [r for r in static_rows if r.get("language") == "html"]

        pages = []
        for html_row in html_files:
            path = str(html_row.get("path", ""))
            slug = "/" if "index.html" in path else f"/{path.split('/')[-1].replace('.html', '')}"
            pages.append(StagingPayloadHabitatPageV1(
                slug=slug,
                title=slug.strip("/").title() or "Home",
                section_count=0,
                file_path=path,
            ))

        return StagingPayloadHabitatV1(
            name=bundle_slug.replace("-", " ").title(),
            slug=bundle_slug,
            framework="unknown",
            theme="default",
            page_count=len(pages),
            file_count=len(static_rows),
            pages=pages,
            libraries=[],
            has_custom_css=False,
            has_custom_js=False,
        )

    name = habitat_meta.get("name", "")
    slug = habitat_meta.get("slug", "")
    framework_config = habitat_meta.get("framework", {})
    framework = framework_config.get("base", "daisyui") if isinstance(framework_config, dict) else "daisyui"
    theme = framework_config.get("theme", "corporate") if isinstance(framework_config, dict) else "corporate"

    pages_raw = habitat_meta.get("pages", [])
    pages = []
    if isinstance(pages_raw, list):
        for p in pages_raw:
            if isinstance(p, dict):
                page_slug = p.get("slug", "/")
                slug_path = "index" if page_slug == "/" else page_slug.strip("/").replace("/", "-")
                pages.append(StagingPayloadHabitatPageV1(
                    slug=page_slug,
                    title=p.get("title", ""),
                    section_count=len(p.get("sections", [])),
                    file_path=f"component/{slug}/{slug_path}.html",
                ))

    libs_raw = habitat_meta.get("libraries", [])
    libraries = []
    if isinstance(libs_raw, list):
        for lib in libs_raw:
            if isinstance(lib, dict):
                lib_name = lib.get("name", "")
                if lib_name:
                    libraries.append(lib_name)

    static_count = sum(
        1 for a in artifact_refs
        if isinstance(a, dict) and is_frontend_file_artifact_role(a.get("role"))
        and isinstance(a.get("bundle_id"), str) and a.get("bundle_id") == slug
    )

    return StagingPayloadHabitatV1(
        name=name,
        slug=slug,
        framework=framework,
        theme=theme,
        page_count=len(pages),
        file_count=static_count,
        pages=pages,
        libraries=libraries,
        has_custom_css=bool(habitat_meta.get("custom_css")),
        has_custom_js=bool(habitat_meta.get("custom_js")),
    )


def _derive_preview_kind(
    artifact_refs: list[Any],
    preview_url: str | None,
) -> Literal["static", "external_url"]:
    has_static = any(
        isinstance(a, dict) and is_frontend_file_artifact_role(a.get("role"))
        for a in artifact_refs
    )
    if has_static:
        return "static"
    pu = (preview_url or "").strip()
    if pu.startswith("http://") or pu.startswith("https://"):
        return "external_url"
    return "static"


def build_staging_snapshot_payload(
    *,
    build_candidate: BuildCandidateRecord,
    evaluation_report: EvaluationReportRecord,
    thread: ThreadRecord,
    build_spec: BuildSpecRecord | None,
    prior_staging_snapshot_id: UUID | None = None,
) -> dict[str, Any]:
    """
    Pure function: same persisted inputs → same JSON-serializable dict.

    No I/O, no generator calls, no raw ``raw_payload_json`` from roles.
    """
    sj: dict[str, Any] = build_spec.spec_json if build_spec is not None else {}
    wsp = dict(build_candidate.working_state_patch_json)
    artifact_refs = list(build_candidate.artifact_refs_json)

    fs = derive_frontend_static_v1(artifact_refs, wsp)
    habitat = derive_habitat_v1(artifact_refs, wsp)

    # Extract block preview anchors from working_state_patch (set by generator_node)
    raw_anchors = wsp.get("block_preview_anchors")
    block_preview_anchors: list[str] = list(raw_anchors) if isinstance(raw_anchors, list) else []

    preview_kind = _derive_preview_kind(artifact_refs, build_candidate.preview_url)

    prior_s = str(prior_staging_snapshot_id) if prior_staging_snapshot_id is not None else None
    reuse_note: str | None = None
    if prior_staging_snapshot_id is not None:
        reuse_note = (
            "Prior staging on this thread: generated images, gallery URLs, and other artifacts "
            "may intentionally reuse the same references across amends."
        )

    spec_summary = StagingPayloadSummaryV1(
        type=sj.get("type") if isinstance(sj.get("type"), str) else None,
        title=sj.get("title") if isinstance(sj.get("title"), str) else None,
    )
    body = StagingSnapshotPayloadV1(
        ids=StagingPayloadIdsV1(
            thread_id=str(build_candidate.thread_id),
            graph_run_id=str(build_candidate.graph_run_id),
            build_candidate_id=str(build_candidate.build_candidate_id),
            evaluation_report_id=str(evaluation_report.evaluation_report_id),
            identity_id=str(thread.identity_id) if thread.identity_id is not None else None,
            build_spec_id=str(build_spec.build_spec_id) if build_spec is not None else None,
            prior_staging_snapshot_id=prior_s,
        ),
        summary=spec_summary,
        evaluation=StagingPayloadEvaluationV1(
            status=evaluation_report.status,
            summary=evaluation_report.summary or "",
            issues=list(evaluation_report.issues_json),
            metrics=dict(evaluation_report.metrics_json),
        ),
        preview=StagingPayloadPreviewV1(
            preview_url=build_candidate.preview_url,
            sandbox_ref=build_candidate.sandbox_ref,
        ),
        artifacts=StagingPayloadArtifactsV1(
            artifact_refs=artifact_refs,
        ),
        metadata=StagingPayloadMetadataV1(
            working_state_patch=wsp,
            frontend_static=fs,
            habitat=habitat,
            preview_kind=preview_kind,
            content_reuse_note=reuse_note,
            block_preview_anchors=block_preview_anchors,
        ),
    )
    return body.model_dump(mode="json")
