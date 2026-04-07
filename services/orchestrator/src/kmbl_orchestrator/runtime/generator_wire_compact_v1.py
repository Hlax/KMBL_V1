"""
Strip large inline file bodies from persisted generator role output (artifact-first wire shape).

Full content remains on ``BuildCandidateRecord.artifact_refs_json`` / workspace; this only compacts
the JSON stored on ``role_invocation.output_payload_json`` for observability and downstream hygiene.

**Workspace-first mode**: When ``workspace_manifest_v1`` + ``sandbox_ref`` are present in the
generator output, the workspace is the authoritative source of truth.  Inline ``artifact_outputs``
content is metadata-only by default for interactive lanes to avoid duplicate payloads.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any

WIRE_COMPACTION_VERSION: int = 2
# Skip stripping tiny strings in proposed_changes (likely labels, not sources).
_PROPOSED_CONTENT_STRIP_MIN_CHARS: int = 512
# Max snippet chars to keep for debugging (workspace-first mode).
_WORKSPACE_FIRST_SNIPPET_MAX: int = 200


def compact_generator_output_payload_for_persistence(
    raw: dict[str, Any],
    *,
    workspace_first: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Deep-copy ``raw`` and remove ``artifact_outputs[].content`` (and large ``proposed_changes`` file bodies).

    When ``workspace_first`` is True, each artifact row also gets a truncated ``content_snippet``
    for debugging, plus a ``digest8`` hash.  This is the default when ``workspace_manifest_v1`` +
    ``sandbox_ref`` are present — workspace files are the single source of truth.

    Returns ``(compacted_payload, telemetry)`` — telemetry has counts only, no content.
    """
    out = copy.deepcopy(raw)
    removed_chars = 0
    rows_touched = 0

    ao = out.get("artifact_outputs")
    if isinstance(ao, list):
        for item in ao:
            if not isinstance(item, dict):
                continue
            rows_touched += 1
            c = item.get("content")
            content_len = 0
            if isinstance(c, str):
                removed_chars += len(c)
                content_len = len(c.encode("utf-8", errors="replace"))
                item["digest8"] = hashlib.sha256(
                    c.encode("utf-8", errors="replace")
                ).hexdigest()[:8]
                if workspace_first:
                    item["content_snippet"] = c[:_WORKSPACE_FIRST_SNIPPET_MAX]
            if "content" in item:
                item.pop("content", None)
            item["content_omitted"] = True
            if content_len:
                item["content_len"] = content_len

    pc = out.get("proposed_changes")
    if isinstance(pc, dict):
        files = pc.get("files")
        if isinstance(files, list):
            for f in files:
                if not isinstance(f, dict):
                    continue
                c = f.get("content")
                if isinstance(c, str) and len(c) >= _PROPOSED_CONTENT_STRIP_MIN_CHARS:
                    removed_chars += len(c)
                    f.pop("content", None)
                    f["content_omitted"] = True
                    f["content_len"] = len(c.encode("utf-8", errors="replace"))

    telemetry: dict[str, Any] = {
        "wire_compaction_version": WIRE_COMPACTION_VERSION,
        "artifact_output_rows_touched": rows_touched,
        "removed_inline_content_char_estimate": removed_chars,
        "workspace_first": workspace_first,
    }
    out["kmbl_generator_wire_compaction_v1"] = {
        "version": WIRE_COMPACTION_VERSION,
        "artifact_outputs_stripped": rows_touched > 0,
        "workspace_first": workspace_first,
        "note": (
            "Inline bodies removed from wire JSON; full artifacts are on build_candidate / workspace."
            if not workspace_first
            else "Workspace-first: inline bodies replaced with metadata + snippets; "
            "workspace files are authoritative source of truth."
        ),
    }
    return out, telemetry


def shape_generator_invocation_output_payload(
    raw: dict[str, Any],
    *,
    persist_raw_for_debug: bool,
    post_normalization: bool,
    workspace_first: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Produce ``role_invocation.output_payload_json`` and compact telemetry.

    Does not mutate ``raw``. When ``persist_raw_for_debug`` is True, returns a deep copy of ``raw``
    (full model output) — use only in non-production debugging; increases storage and bypasses
    wire compaction on the invocation row.

    When ``workspace_first`` is True, artifact rows get metadata + snippets only (workspace
    files are the single source of truth).

    Telemetry dict is counts/flags only (safe for routing_metadata).
    """
    base: dict[str, Any] = {
        "debug_raw_generator_output": persist_raw_for_debug,
        "post_normalization_save": post_normalization,
        "workspace_first": workspace_first,
    }
    if persist_raw_for_debug:
        tm = {
            **base,
            "wire_compacted": False,
            "wire_compaction_skipped": True,
            "blast_radius_note": (
                "role_invocation.output_payload_json may contain full artifact bodies; "
                "disable kmbl_persist_raw_generator_output_for_debug for default compact persistence."
            ),
        }
        return copy.deepcopy(raw), tm

    compact, wire_meta = compact_generator_output_payload_for_persistence(
        raw, workspace_first=workspace_first,
    )
    tm: dict[str, Any] = {
        **base,
        "wire_compacted": True,
        "wire_compaction": wire_meta,
    }
    if not post_normalization:
        tm["first_durable_save_pre_normalize"] = True
    return compact, tm


def wire_compaction_routing_marker(
    *,
    persist_raw_for_debug: bool,
    wire_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    """Value for ``routing_metadata_json['kmbl_generator_wire_compaction_v1']`` (always JSON-safe)."""
    if persist_raw_for_debug:
        return {
            "skipped": True,
            "reason": "kmbl_persist_raw_generator_output_for_debug",
        }
    return dict(wire_meta or {})
