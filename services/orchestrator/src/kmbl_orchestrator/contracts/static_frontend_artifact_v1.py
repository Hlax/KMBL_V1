"""
Lightweight static front-end files for generator ``artifact_outputs``.

Convention: paths under ``component/`` with ``.html`` / ``.css`` / ``.js`` suffixes
(e.g. ``component/preview/index.html``). KMBL normalizes and persists these on
``build_candidate.artifact_refs_json`` alongside other roles (e.g. gallery images).

This is not a component framework — only a stable, review-friendly shape for
simple HTML/CSS/JS bundles.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_log = logging.getLogger(__name__)

_PATH_RE = re.compile(
    r"^component/(?:[a-zA-Z0-9][a-zA-Z0-9_-]*/)*[a-zA-Z0-9][a-zA-Z0-9_-]*\.(html|css|js|json|glsl|wgsl|vert|frag|splat|ply)$"
)
_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_MAX_CONTENT_BYTES = 256 * 1024


def _infer_language_from_path(
    path: str,
) -> Literal["html", "css", "js", "json", "glsl", "wgsl", "vert", "frag", "splat", "ply"]:
    lower = path.lower()
    if lower.endswith(".html"):
        return "html"
    if lower.endswith(".css"):
        return "css"
    if lower.endswith(".js"):
        return "js"
    if lower.endswith(".json"):
        return "json"
    if lower.endswith(".glsl"):
        return "glsl"
    if lower.endswith(".wgsl"):
        return "wgsl"
    if lower.endswith(".vert"):
        return "vert"
    if lower.endswith(".frag"):
        return "frag"
    if lower.endswith(".splat"):
        return "splat"
    if lower.endswith(".ply"):
        return "ply"
    raise ValueError("cannot infer language from path")


class StaticFrontendFileArtifactV1(BaseModel):
    """One static file in a simple multi-file UI bundle."""

    model_config = ConfigDict(extra="ignore")

    role: Literal["static_frontend_file_v1"]
    path: str = Field(min_length=1, max_length=512)
    language: Literal["html", "css", "js", "json", "glsl", "wgsl", "vert", "frag", "splat", "ply"]
    content: str = Field(min_length=1, max_length=_MAX_CONTENT_BYTES)
    bundle_id: str | None = Field(default=None, max_length=64)
    previewable: bool | None = None
    entry_for_preview: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_path_language_bundle(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        # Map common aliases to canonical field names
        if d.get("path") is None and d.get("file_path") is not None:
            d["path"] = d.pop("file_path")
        if d.get("path") is None and d.get("file") is not None:
            d["path"] = d.pop("file")
        if isinstance(d.get("path"), str):
            d["path"] = d["path"].strip().replace("\\", "/")
        bid = d.get("bundle_id")
        if bid is None or bid == "":
            d["bundle_id"] = None
        elif isinstance(bid, str):
            s = bid.strip()
            if not s:
                d["bundle_id"] = None
            elif not _KEY_RE.match(s):
                raise ValueError(
                    "bundle_id must match ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$ or be null"
                )
            else:
                d["bundle_id"] = s
        if d.get("language") is None and isinstance(d.get("path"), str):
            try:
                d["language"] = _infer_language_from_path(d["path"])
            except ValueError as e:
                raise ValueError(
                    "language is required if path has no recognized component/ file suffix"
                ) from e
        return d

    @model_validator(mode="after")
    def path_shape_language_and_preview_defaults(self) -> StaticFrontendFileArtifactV1:
        p = self.path
        if ".." in p or p.startswith("/") or "//" in p:
            raise ValueError("path must be a safe relative component/ path")
        if not p.startswith("component/"):
            raise ValueError('path must start with "component/"')
        if not _PATH_RE.match(p):
            raise ValueError(
                "path must match component/<segments>/<name> with a supported extension "
                "(html|css|js|json|glsl|wgsl|vert|frag|splat|ply) "
                "(no .., no absolute paths)"
            )
        inferred = _infer_language_from_path(p)
        if self.language != inferred:
            raise ValueError(f"language {self.language!r} does not match path extension")
        pv = (self.language == "html") if self.previewable is None else self.previewable
        return self.model_copy(update={"previewable": pv})


class InteractiveFrontendAppArtifactV1(StaticFrontendFileArtifactV1):
    """Same on-disk shape as static files; distinct role for interactive / richer JS (bounded, no bundler)."""

    role: Literal["interactive_frontend_app_v1"]  # type: ignore[assignment]


def normalize_static_frontend_artifact_outputs_list(seq: list[Any]) -> list[Any]:
    """
    Validate ``static_frontend_file_v1`` and ``interactive_frontend_app_v1`` dicts; pass
    through other entries unchanged.

    Skips malformed rows with a warning rather than crashing the entire
    normalization pipeline.  Duplicate paths keep the first occurrence.
    Multiple ``entry_for_preview`` flags per bundle are resolved by keeping only
    the first.
    """
    out: list[Any] = []
    static_paths: set[str] = set()
    by_bundle: dict[str | None, list[tuple[str, bool]]] = {}

    for item in seq:
        role = item.get("role") if isinstance(item, dict) else None
        if isinstance(item, dict) and role == "static_frontend_file_v1":
            try:
                model = StaticFrontendFileArtifactV1.model_validate(item)
            except Exception as exc:
                _log.warning(
                    "static_frontend_file_v1 row skipped (validation): %s — %s",
                    item.get("path", "<no path>"),
                    exc,
                )
                continue
            dumped = model.model_dump(mode="json")
            path = str(dumped["path"])
            if path in static_paths:
                _log.warning(
                    "static_frontend_file_v1 duplicate path skipped: %s", path,
                )
                continue
            static_paths.add(path)
            bid = dumped.get("bundle_id")
            bkey: str | None = bid if isinstance(bid, str) else None
            by_bundle.setdefault(bkey, []).append((path, bool(dumped.get("entry_for_preview"))))
            out.append(dumped)
        elif isinstance(item, dict) and role == "interactive_frontend_app_v1":
            try:
                imodel = InteractiveFrontendAppArtifactV1.model_validate(item)
            except Exception as exc:
                _log.warning(
                    "interactive_frontend_app_v1 row skipped (validation): %s — %s",
                    item.get("path", "<no path>"),
                    exc,
                )
                continue
            dumped_i = imodel.model_dump(mode="json")
            path_i = str(dumped_i["path"])
            if path_i in static_paths:
                _log.warning(
                    "interactive_frontend_app_v1 duplicate path skipped: %s", path_i,
                )
                continue
            static_paths.add(path_i)
            bid_i = dumped_i.get("bundle_id")
            bkey_i: str | None = bid_i if isinstance(bid_i, str) else None
            by_bundle.setdefault(bkey_i, []).append(
                (path_i, bool(dumped_i.get("entry_for_preview")))
            )
            out.append(dumped_i)
        else:
            out.append(item)

    for bkey, rows in by_bundle.items():
        entries = [p for p, e in rows if e]
        if len(entries) > 1:
            _log.warning(
                "multiple entry_for_preview in bundle %s — keeping first: %s",
                "default" if bkey is None else repr(bkey),
                entries,
            )

    return out


def normalize_combined_artifact_outputs_list(raw: Any) -> list[Any]:
    """
    Combined normalization pipeline for all artifact types.
    
    Order: gallery images → universal images → html blocks → static frontend files
    """
    gal = _gallery_normalize(raw)
    img = _image_artifact_normalize(gal)
    blk = _html_block_normalize(img)
    return normalize_static_frontend_artifact_outputs_list(blk)


def _gallery_normalize(raw: Any) -> list[Any]:
    from kmbl_orchestrator.contracts.gallery_image_artifact_v1 import (
        normalize_gallery_artifact_outputs_list,
    )

    return normalize_gallery_artifact_outputs_list(raw)


def _image_artifact_normalize(raw: list[Any]) -> list[Any]:
    from kmbl_orchestrator.contracts.image_artifact_v1 import (
        normalize_image_artifact_outputs_list,
    )

    return normalize_image_artifact_outputs_list(raw)


def _html_block_normalize(raw: list[Any]) -> list[Any]:
    from kmbl_orchestrator.contracts.html_block_artifact_v1 import (
        normalize_html_block_outputs_list,
    )

    return normalize_html_block_outputs_list(raw)
