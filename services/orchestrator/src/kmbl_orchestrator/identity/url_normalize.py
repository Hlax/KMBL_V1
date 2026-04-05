"""URL normalization for consistent crawl tracking.

Ensures the same page visited via different URL forms maps to a single canonical key.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, urlunparse


# Query params to strip (analytics, tracking, session)
_STRIP_PARAMS_RE = re.compile(
    r"(?:^|&)(?:utm_\w+|fbclid|gclid|ref|source|mc_\w+|_ga|sessionid)=[^&]*",
    re.IGNORECASE,
)


def normalize_url(url: str) -> str:
    """Return a canonical form of *url* suitable for deduplication.

    Rules:
    - Lowercase scheme and host.
    - Strip trailing slash from path (unless path is exactly '/').
    - Remove default ports (80 for http, 443 for https).
    - Remove fragment (#...).
    - Strip known tracking query params (utm_*, fbclid, gclid, etc.).
    - Collapse consecutive slashes in path.
    """
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    host = (parsed.hostname or "").lower()

    # Remove default ports
    port = parsed.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    netloc = host if port is None else f"{host}:{port}"

    # Normalize path
    path = parsed.path or "/"
    # Collapse consecutive slashes
    path = re.sub(r"/+", "/", path)
    # Strip trailing slash (but keep "/" for root)
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # Strip tracking params from query
    query = parsed.query
    if query:
        query = _STRIP_PARAMS_RE.sub("", query).strip("&")

    return urlunparse((scheme, netloc, path, "", query, ""))


def is_same_domain(url: str, base_url: str) -> bool:
    """Check if url belongs to the same domain as base_url."""
    try:
        url_host = urlparse(url).hostname or ""
        base_host = urlparse(base_url).hostname or ""
        # Strip www. prefix for comparison
        url_host = url_host.lower().removeprefix("www.")
        base_host = base_host.lower().removeprefix("www.")
        return url_host == base_host
    except Exception:
        return False


_IGNORE_SCHEMES = ("javascript:", "mailto:", "tel:", "data:")


def resolve_url(href: str, base_url: str) -> str | None:
    """Resolve a potentially relative href against base_url.

    Returns normalized absolute URL or None if unresolvable.
    """
    if not isinstance(href, str) or not href or href.startswith(_IGNORE_SCHEMES):
        return None
    try:
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            return None
        return normalize_url(absolute)
    except Exception:
        return None
