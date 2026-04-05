"""Generator workspace_manifest_v1 — file list for orchestrator-side ingest."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceManifestFileV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        min_length=1,
        description=(
            "Logical static path under component/ (same as static_frontend_file_v1.path), "
            "e.g. component/preview/index.html"
        ),
    )
    sha256: str | None = Field(
        default=None,
        description="Optional hex digest; orchestrator verifies after read.",
    )


class WorkspaceManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    files: list[WorkspaceManifestFileV1] = Field(min_length=1)
    entry_html: str | None = Field(
        default=None,
        description="Optional component/… path marked entry_for_preview after ingest.",
    )
