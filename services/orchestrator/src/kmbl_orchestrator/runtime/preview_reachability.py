"""Classify preview URLs for operator browsing vs OpenClaw / browser MCP reachability."""

from __future__ import annotations

import ipaddress
from typing import Any, Literal
from urllib.parse import urlparse

PreviewHostClass = Literal["localhost", "private_ip", "public_host", "unknown"]

_LOCALHOST_NAMES = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        "0:0:0:0:0:0:0:1",
    }
)


def classify_preview_url_host(url: str) -> PreviewHostClass:
    """
    Bucket the preview URL's host for policy and telemetry.

    - ``localhost``: loopback IPs / ``localhost``
    - ``private_ip``: non-loopback non-globally-routable addresses (RFC1918, link-local, ULA, …)
    - ``public_host``: hostname or global unicast IP we treat as gateway-reachable
    - ``unknown``: unparseable or missing host
    """
    raw = url.strip() if isinstance(url, str) else ""
    if not raw:
        return "unknown"
    try:
        p = urlparse(raw)
    except ValueError:
        return "unknown"
    host = (p.hostname or "").strip().lower()
    if not host:
        return "unknown"
    if host in _LOCALHOST_NAMES:
        return "localhost"
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        if host.endswith(".localhost"):
            return "localhost"
        if host.endswith(".local") or host.endswith(".internal"):
            return "private_ip"
        return "public_host"
    if addr.is_loopback:
        return "localhost"
    if addr.is_private or addr.is_link_local or addr.is_reserved:
        return "private_ip"
    if addr.is_multicast or addr.is_unspecified:
        return "private_ip"
    return "public_host"


def preview_host_blocked_by_openclaw_default(url: str) -> bool:
    """True when OpenClaw-style gateways typically block fetches to this URL."""
    return classify_preview_url_host(url) in ("localhost", "private_ip")


def summary_v2_supports_offline_evaluator_grounding(bc_slim: dict[str, Any]) -> bool:
    """Manifest-first / preview vertical: artifact summary can substitute for live browser grounding."""
    s2 = bc_slim.get("kmbl_build_candidate_summary_v2")
    if not isinstance(s2, dict):
        return False
    eps = s2.get("entrypoints")
    if not isinstance(eps, list) or len(eps) == 0:
        return False
    pr = s2.get("preview_readiness") if isinstance(s2.get("preview_readiness"), dict) else {}
    return bool(pr.get("has_resolved_entrypoints"))


def manifest_first_evaluator_grounding_satisfied(
    preview_resolution: dict[str, Any],
    bc_slim: dict[str, Any],
) -> bool:
    """
    Whether manifest-first evaluator may run without a live browser-reachable preview URL.

    Live absolute ``preview_url`` (browser) still satisfies immediately; otherwise a complete
    summary_v2 preview readiness path avoids demanding runtime-only proof OpenClaw cannot obtain.
    """
    if preview_resolution.get("preview_url") and preview_resolution.get("preview_url_is_absolute"):
        return True
    return summary_v2_supports_offline_evaluator_grounding(bc_slim)
