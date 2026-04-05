"""Canonical site key for sharing crawl memory across identities on the same public site."""

from __future__ import annotations

from urllib.parse import urlparse

from kmbl_orchestrator.identity.url_normalize import normalize_url


def canonical_site_key(url: str) -> str:
    """Stable key: normalized hostname without leading ``www.``, lowercased.

    Same registrable site should map to one key for v1 (hostname-based, not PSL-aware).
    """
    nu = normalize_url(url)
    parsed = urlparse(nu)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return "unknown"
    return host
