"""HTML block artifact for incremental, section-level generator amendments.

Instead of regenerating the entire page, generators can emit a targeted block
that replaces or extends a specific section (identified by CSS id or ``__body__``)
within an existing ``static_frontend_file_v1`` HTML file.

The orchestrator applies blocks to the current working-staging HTML and produces
merged ``static_frontend_file_v1`` artifacts so the evaluator and staging pipeline
work normally.  The original ``html_block_v1`` artifacts are retained in
``artifact_refs_json`` for provenance and preview-anchor derivation.

**Generator contract**::

    {
        "artifact_outputs": [
            {
                "role": "html_block_v1",
                "block_id": "hero",
                "target_path": "component/preview/index.html",
                "operation": "replace",
                "target_selector": "#hero",
                "content": "<section id='hero'><h1>New Hero</h1></section>",
                "preview_anchor": "hero"
            }
        ]
    }

``target_selector`` must be a CSS id selector (``#hero``) or the special
value ``__body__``.  For ``replace``, the element with that id is replaced.
For ``append_to_body`` / ``prepend_to_body``, content is inserted relative
to ``<body>``.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_log = logging.getLogger(__name__)

_BLOCK_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
_PATH_RE = re.compile(
    r"^component/(?:[a-zA-Z0-9][a-zA-Z0-9_-]*/)*[a-zA-Z0-9][a-zA-Z0-9_-]*\.html$"
)
_SELECTOR_RE = re.compile(r"^#[a-zA-Z][a-zA-Z0-9_-]{0,127}$|^__body__$")

_MAX_BLOCK_CONTENT_BYTES = 256 * 1024


class HtmlBlockArtifactV1(BaseModel):
    """Incremental HTML block targeting a section within an existing file.

    The ``content`` replaces or is inserted relative to the HTML element whose
    ``id`` attribute matches ``target_selector``.  When ``target_selector`` is
    ``__body__``, content is appended/prepended to the document body.
    """

    model_config = ConfigDict(extra="ignore")

    role: Literal["html_block_v1"]
    block_id: str = Field(min_length=1, max_length=64)
    target_path: str = Field(min_length=1, max_length=512)
    operation: Literal["replace", "append_to_body", "prepend_to_body"] = "replace"
    target_selector: str = Field(default="__body__", min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=_MAX_BLOCK_CONTENT_BYTES)
    preview_anchor: str | None = Field(default=None, max_length=128)
    bundle_id: str | None = Field(default=None, max_length=64)

    @field_validator("block_id")
    @classmethod
    def validate_block_id(cls, v: str) -> str:
        if not _BLOCK_ID_RE.match(v):
            raise ValueError(
                "block_id must start with a letter and contain only "
                "alphanumeric, underscore, or hyphen characters"
            )
        return v

    @field_validator("target_path")
    @classmethod
    def validate_target_path(cls, v: str) -> str:
        v = v.strip().replace("\\", "/")
        if ".." in v or v.startswith("/") or "//" in v:
            raise ValueError("target_path must be a safe relative component/ path")
        if not _PATH_RE.match(v):
            raise ValueError(
                "target_path must match component/<segments>/<name>.html (only .html files)"
            )
        return v

    @field_validator("target_selector")
    @classmethod
    def validate_target_selector(cls, v: str) -> str:
        if not _SELECTOR_RE.match(v):
            raise ValueError(
                "target_selector must be a CSS id selector like '#hero' "
                "or the special value '__body__'"
            )
        return v

    @property
    def effective_preview_anchor(self) -> str:
        """Fragment identifier to append to the staging preview URL."""
        if self.preview_anchor and self.preview_anchor.strip():
            return self.preview_anchor.strip().lstrip("#")
        if self.target_selector and self.target_selector.startswith("#"):
            return self.target_selector.lstrip("#")
        return self.block_id


def normalize_html_block_artifact(item: dict[str, Any]) -> dict[str, Any] | None:
    """Validate and normalize a single ``html_block_v1`` dict.

    Returns the normalized dict or ``None`` if validation fails (with a warning
    logged) — matches the skipping pattern used for other artifact types.
    """
    if not isinstance(item, dict):
        return None
    if item.get("role") != "html_block_v1":
        return None
    try:
        model = HtmlBlockArtifactV1.model_validate(item)
        return model.model_dump(mode="json")
    except Exception as exc:
        _log.warning(
            "html_block_v1 skipped (validation): block_id=%s error=%s",
            item.get("block_id", "<no block_id>"),
            exc,
        )
        return None


def normalize_html_block_outputs_list(seq: list[Any]) -> list[Any]:
    """Validate ``html_block_v1`` dicts in a list; pass through other entries unchanged.

    Skips malformed rows with a warning.  Deduplicates by ``block_id``.
    """
    out: list[Any] = []
    seen_ids: set[str] = set()

    for item in seq:
        if isinstance(item, dict) and item.get("role") == "html_block_v1":
            normalized = normalize_html_block_artifact(item)
            if normalized is None:
                continue
            bid = str(normalized["block_id"])
            if bid in seen_ids:
                _log.warning("html_block_v1 duplicate block_id skipped: %s", bid)
                continue
            seen_ids.add(bid)
            out.append(normalized)
        else:
            out.append(item)

    return out
