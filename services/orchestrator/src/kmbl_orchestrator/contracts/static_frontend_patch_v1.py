"""
Optional working-state hint: which HTML file is the preview entry for a static bundle.

Lives under ``proposed_changes`` / ``updated_state`` (whichever becomes the patch) as
``static_frontend_preview_v1``. Generator may omit this — staging still derives preview
hints from ``entry_for_preview`` on ``static_frontend_file_v1`` artifacts.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kmbl_orchestrator.contracts.frontend_artifact_roles import is_frontend_file_artifact_role

_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_PATH_RE = re.compile(
    r"^component/(?:[a-zA-Z0-9][a-zA-Z0-9_-]*/)*[a-zA-Z0-9][a-zA-Z0-9_-]*\.html$"
)


class StaticFrontendPreviewV1(BaseModel):
    """Points at one HTML artifact path; optional bundle alignment."""

    model_config = ConfigDict(extra="forbid")

    entry_path: str = Field(min_length=1, max_length=512)
    bundle_id: str | None = Field(default=None, max_length=64)

    @field_validator("entry_path", mode="before")
    @classmethod
    def norm_path(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().replace("\\", "/")
        return v

    @field_validator("bundle_id", mode="before")
    @classmethod
    def norm_bundle(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            if not _KEY_RE.match(s):
                raise ValueError("bundle_id must be a slug or null")
            return s
        return v

    @field_validator("entry_path")
    @classmethod
    def entry_must_be_html_under_component(cls, v: str) -> str:
        if ".." in v or v.startswith("/") or "//" in v:
            raise ValueError("entry_path must be a safe relative path")
        if not v.startswith("component/"):
            raise ValueError('entry_path must start with "component/"')
        if not _PATH_RE.match(v):
            raise ValueError("entry_path must be a component/ path ending in .html")
        return v


def normalize_static_frontend_preview_in_patch(
    patch: dict[str, Any], normalized_artifacts: list[Any]
) -> dict[str, Any]:
    """
    Validate ``static_frontend_preview_v1`` if present and ensure ``entry_path`` exists
    on a static or interactive frontend file artifact (and ``bundle_id`` matches when set).
    """
    raw = patch.get("static_frontend_preview_v1")
    if raw is None:
        return patch
    if not isinstance(raw, dict):
        raise ValueError("static_frontend_preview_v1 must be an object")
    model = StaticFrontendPreviewV1.model_validate(raw)

    by_path: dict[str, dict[str, Any]] = {}
    for a in normalized_artifacts:
        if not isinstance(a, dict):
            continue
        if not is_frontend_file_artifact_role(a.get("role")):
            continue
        p = a.get("path")
        if isinstance(p, str) and p.strip():
            by_path[p.strip()] = a

    ep = model.entry_path
    if ep not in by_path:
        raise ValueError(
            f"static_frontend_preview_v1 entry_path {ep!r} has no matching frontend file artifact"
        )
    art = by_path[ep]
    if str(art.get("language")) != "html":
        raise ValueError("static_frontend_preview_v1 entry_path must reference an html artifact")
    bid = model.bundle_id
    if bid is not None:
        ab = art.get("bundle_id")
        ab_s = ab if isinstance(ab, str) else None
        if ab_s != bid:
            raise ValueError(
                "static_frontend_preview_v1 bundle_id does not match the artifact at entry_path"
            )

    out = dict(patch)
    out["static_frontend_preview_v1"] = model.model_dump(mode="json")
    return out
