"""Publication delivery — serialize a publication snapshot into a static HTML artefact.

The *minimal viable* delivery model: extract the primary HTML file from the
snapshot's ``payload_json``, write it to a configured output directory or
return it as a string for callers that handle their own storage/CDN upload.

Future expansion points (not yet implemented):
- Upload to Supabase Storage bucket (set ``KMBL_PUBLICATION_STORAGE_BUCKET``)
- Upload to S3 / R2 / GCS (configured via separate env keys)
- Trigger a CDN cache-purge after delivery

Usage (API layer)::

    from kmbl_orchestrator.publication.delivery import (
        DeliveryResult,
        deliver_publication_snapshot,
    )

    result = deliver_publication_snapshot(snapshot, settings=settings)
    if result.delivered:
        # update publication record with result.public_url
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from kmbl_orchestrator.domain import PublicationSnapshotRecord
from kmbl_orchestrator.staging.static_preview_assembly import (
    assemble_static_preview_html,
    resolve_static_preview_entry_path,
)

_log = logging.getLogger(__name__)

_SAFE_SLUG_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _safe_slug(raw: str, max_len: int = 40) -> str:
    """Normalise an arbitrary string into a filesystem-safe slug."""
    return _SAFE_SLUG_RE.sub("_", raw)[:max_len]


@dataclass
class DeliveryResult:
    """Result of a publication delivery attempt."""

    delivered: bool
    """True when a usable HTML artefact was produced and (if a path was configured) written."""

    html_content: str = ""
    """The assembled HTML string (always populated when ``delivered=True``)."""

    public_url: str | None = None
    """Public-facing URL when the artefact was uploaded / served from a known base URL."""

    output_path: str | None = None
    """Filesystem path where the HTML was written (when an output dir is configured)."""

    reason: str = ""
    """Human-readable reason for success or failure."""

    warnings: list[str] = field(default_factory=list)
    """Non-fatal issues encountered during delivery."""


def deliver_publication_snapshot(
    snapshot: PublicationSnapshotRecord,
    *,
    output_dir: str | None = None,
    base_url: str | None = None,
) -> DeliveryResult:
    """Serialize a publication snapshot to static HTML.

    Parameters
    ----------
    snapshot:
        The immutable publication record to deliver.
    output_dir:
        Optional filesystem directory to write ``<snapshot_id>.html`` into.
        Falls back to the ``KMBL_PUBLICATION_OUTPUT_DIR`` environment variable.
        When neither is set the HTML is returned in-memory only.
    base_url:
        Optional public-facing base URL for computing ``public_url``.
        Falls back to ``KMBL_PUBLICATION_BASE_URL`` env var.

    Returns
    -------
    DeliveryResult
        Always returned (never raises); check ``delivered`` and ``reason``.
    """
    warnings: list[str] = []
    payload = snapshot.payload_json
    if not isinstance(payload, dict) or not payload:
        return DeliveryResult(
            delivered=False,
            reason="publication snapshot has empty or invalid payload_json",
        )

    # --- Resolve entry path ---
    entry_path, entry_err = resolve_static_preview_entry_path(payload)
    if entry_path is None:
        return DeliveryResult(
            delivered=False,
            reason=f"no previewable HTML entry found in publication snapshot payload: {entry_err}",
        )

    # --- Assemble HTML ---
    html, err_code = assemble_static_preview_html(payload, entry_path=entry_path)
    if not html:
        return DeliveryResult(
            delivered=False,
            reason=f"assemble_static_preview_html returned empty: {err_code}",
        )

    # --- Determine output location ---
    eff_output_dir = output_dir or os.environ.get("KMBL_PUBLICATION_OUTPUT_DIR", "").strip()
    eff_base_url = base_url or os.environ.get("KMBL_PUBLICATION_BASE_URL", "").strip()

    snapshot_id_str = str(snapshot.publication_snapshot_id)
    filename = f"{snapshot_id_str}.html"
    written_path: str | None = None

    if eff_output_dir:
        try:
            out_dir = Path(eff_output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / filename
            out_file.write_text(html, encoding="utf-8")
            written_path = str(out_file)
            _log.info(
                "publication_delivery written snapshot_id=%s path=%s bytes=%d",
                snapshot_id_str,
                written_path,
                len(html),
            )
        except OSError as exc:
            warnings.append(f"filesystem write failed: {exc}")
            _log.warning("publication_delivery filesystem write failed: %s", exc)

    # --- Build public URL ---
    public_url: str | None = None
    if eff_base_url and eff_base_url.rstrip("/"):
        public_url = f"{eff_base_url.rstrip('/')}/{filename}"

    return DeliveryResult(
        delivered=True,
        html_content=html,
        public_url=public_url,
        output_path=written_path,
        reason="ok",
        warnings=warnings,
    )
