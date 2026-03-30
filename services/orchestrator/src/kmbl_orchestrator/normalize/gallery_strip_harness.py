"""
Deterministic harness checks for ``ui_gallery_strip_v1`` merged into persisted evaluation.

Runs after the KiloClaw evaluator normalizes — adds metrics and optional issues without
replacing the model evaluator's summary unless configured to downgrade status.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from typing import Any

from kmbl_orchestrator.domain import BuildCandidateRecord, EvaluationReportRecord

_USER_AGENT = "KMBL-Orchestrator/gallery-strip-harness"


def _probe_url_reachable(url: str, timeout_sec: float = 4.0) -> bool:
    """Best-effort HEAD then GET; many CDNs block HEAD."""
    headers = {"User-Agent": _USER_AGENT}
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:  # noqa: S310
                code = getattr(resp, "status", None) or resp.getcode()
                return isinstance(code, int) and 200 <= code < 400
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError):
            continue
    return False


def _strip_from_patch(patch: dict[str, Any]) -> dict[str, Any] | None:
    raw = patch.get("ui_gallery_strip_v1")
    return raw if isinstance(raw, dict) else None


def merge_gallery_strip_harness_checks(
    report: EvaluationReportRecord,
    candidate: BuildCandidateRecord,
    *,
    probe_urls: bool | None = None,
) -> EvaluationReportRecord:
    """
    If the candidate patch contains ``ui_gallery_strip_v1``, merge metrics and optional issues.

    URL probing is off by default (set env ORCHESTRATOR_GALLERY_STRIP_PROBE_URLS=1 or pass
    probe_urls=True) to keep CI deterministic.
    """
    patch = dict(candidate.working_state_patch_json)
    strip = _strip_from_patch(patch)
    if strip is None:
        return report

    items = strip.get("items")
    if not isinstance(items, list):
        return report

    if probe_urls is None:
        probe_urls = os.environ.get("ORCHESTRATOR_GALLERY_STRIP_PROBE_URLS", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )

    metrics = dict(report.metrics_json)
    issues = list(report.issues_json)

    n = len(items)
    metrics["gallery_strip_v1_item_count"] = n
    metrics["gallery_strip_v1_present"] = True

    href_http_ok = True
    image_urls: list[str] = []
    thumb_urls: list[str] = []
    artifact_keys: list[str] = []

    for it in items:
        if not isinstance(it, dict):
            continue
        h = it.get("href")
        if isinstance(h, str) and h.strip():
            if not (h.startswith("http://") or h.startswith("https://")):
                href_http_ok = False
        iu = it.get("image_url")
        if isinstance(iu, str) and iu.strip():
            image_urls.append(iu.strip())
        tu = it.get("image_thumb_url")
        if isinstance(tu, str) and tu.strip():
            thumb_urls.append(tu.strip())
        ak = it.get("image_artifact_key")
        if isinstance(ak, str) and ak.strip():
            artifact_keys.append(ak.strip())

    metrics["gallery_strip_v1_href_all_http"] = href_http_ok
    metrics["gallery_strip_v1_items_with_images"] = len(image_urls)
    metrics["gallery_strip_v1_items_with_artifact_keys"] = len(artifact_keys)

    labels = [str(it.get("label", "")).strip() for it in items if isinstance(it, dict)]
    metrics["gallery_strip_v1_all_items_labeled"] = all(len(x) > 0 for x in labels) and len(
        labels
    ) == n
    caption_or_image = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        cap = it.get("caption")
        img = it.get("image_url")
        has_cap = isinstance(cap, str) and cap.strip()
        has_img = isinstance(img, str) and img.strip()
        if has_cap or has_img:
            caption_or_image += 1
    metrics["gallery_strip_v1_items_with_caption_or_image"] = caption_or_image

    metrics["gallery_strip_v1_narrow_layout_ok"] = n <= 6

    probe_failures = 0
    if probe_urls:
        to_check = list(dict.fromkeys(image_urls + thumb_urls))
        ok_count = 0
        for u in to_check:
            if _probe_url_reachable(u):
                ok_count += 1
            else:
                probe_failures += 1
                issues.append(f"gallery_strip_harness: image URL not reachable (probe): {u}")
        metrics["gallery_strip_v1_url_probe_checked"] = len(to_check)
        metrics["gallery_strip_v1_url_probe_ok_count"] = ok_count
        metrics["gallery_strip_v1_url_probe_failures"] = probe_failures
    else:
        metrics["gallery_strip_v1_url_probe_checked"] = 0
        metrics["gallery_strip_v1_url_probe_skipped"] = True

    if not href_http_ok:
        issues.append("gallery_strip_harness: non-http(s) href on strip item")

    status = report.status
    summary = report.summary or ""
    if probe_failures > 0 and status == "pass":
        status = "partial"
        if summary:
            summary = f"{summary} [gallery_strip_harness: URL probe issues]"
        else:
            summary = "gallery_strip_harness: URL probe reported unreachable image(s)"

    return report.model_copy(
        update={
            "status": status,
            "summary": summary,
            "issues_json": issues,
            "metrics_json": metrics,
        }
    )
