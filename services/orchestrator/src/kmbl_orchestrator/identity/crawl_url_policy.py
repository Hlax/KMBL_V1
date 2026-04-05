"""Heuristic filters to keep crawl frontiers free of low-value / drift-prone URLs."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from kmbl_orchestrator.identity.url_normalize import is_same_domain, normalize_url

# Hosts that are almost never useful for design grounding (social, auth, app stores).
_LOW_VALUE_HOST_SUFFIXES: tuple[str, ...] = (
    "linkedin.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "tiktok.com",
    "pinterest.com",
    "reddit.com",
    "t.co",
    "youtube.com",
    "youtu.be",
    "google.com",
    "goo.gl",
    "bing.com",
    "apple.com",
    "play.google.com",
    "apps.apple.com",
)

# Path substrings that usually indicate legal, auth, feeds, or admin — not design pages.
_LOW_VALUE_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"/(login|signin|sign-in|signup|sign-up|register|auth|oauth|sso)(/|$)", re.I),
    re.compile(r"/(logout|log-out)(/|$)", re.I),
    re.compile(r"/(cart|checkout|account|my-account|billing)(/|$)", re.I),
    re.compile(r"/(privacy|terms|legal|disclaimer|cookies|cookie-policy|gdpr)(/|$)", re.I),
    re.compile(r"/(wp-admin|wp-login)(/|$)", re.I),
    re.compile(r"/\.(xml|rss|atom)$", re.I),
    re.compile(r"/(feed|rss|atom)(/|$)", re.I),
    re.compile(r"/cdn-cgi/", re.I),
)


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def is_low_value_crawl_url(url: str) -> bool:
    """Return True when URL is unlikely to help identity/design planning (heuristic)."""
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return True
    try:
        path = urlparse(url).path or ""
    except Exception:
        return True

    host = _host(url)
    if not host:
        return True

    for suf in _LOW_VALUE_HOST_SUFFIXES:
        if host == suf or host.endswith("." + suf):
            return True

    for pat in _LOW_VALUE_PATH_PATTERNS:
        if pat.search(path):
            return True

    return False


def filter_frontier_candidate_urls(
    urls: list[str],
    *,
    root_url: str,
) -> list[str]:
    """Drop junk URLs before enqueueing internal frontier; preserve order, dedupe."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in urls:
        try:
            n = normalize_url(raw)
        except Exception:
            continue
        if n in seen:
            continue
        if not is_same_domain(n, root_url):
            continue
        if is_low_value_crawl_url(n):
            continue
        seen.add(n)
        out.append(n)
    return out
