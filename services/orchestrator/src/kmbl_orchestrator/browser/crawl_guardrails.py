"""Bounded crawl policy: same-domain portfolio, allowlisted inspiration, caps."""

from __future__ import annotations

from urllib.parse import urlparse

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import CrawlStateRecord
from kmbl_orchestrator.identity.url_normalize import is_same_domain, normalize_url


def _host_key(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def parse_inspiration_allowlist(settings: Settings) -> set[str]:
    """Hosts from ``kmbl_playwright_inspiration_domains`` (comma-separated)."""
    raw = (settings.kmbl_playwright_inspiration_domains or "").strip()
    if not raw:
        return set()
    hosts: set[str] = set()
    for part in raw.split(","):
        p = part.strip().lower()
        if not p:
            continue
        if "://" in p:
            p = _host_key(p)
        else:
            p = p.removeprefix("www.")
        if p:
            hosts.add(p)
    return hosts


def classify_source_kind(state: CrawlStateRecord, url: str) -> str:
    """``portfolio_internal`` vs ``inspiration_external`` from crawl state."""
    if is_same_domain(url, state.root_url):
        return "portfolio_internal"
    return "inspiration_external"


def allowed_inspiration_hosts(settings: Settings) -> set[str]:
    """Hosts allowed for ``inspiration_external`` visits (configured allowlist only)."""
    return parse_inspiration_allowlist(settings)


def url_passes_grounded_visit(
    state: CrawlStateRecord,
    url: str,
    *,
    source_kind: str,
    settings: Settings,
) -> tuple[bool, str]:
    """Return (allowed, reason_if_blocked)."""
    try:
        norm = normalize_url(url)
    except Exception:
        return False, "normalize_failed"

    if source_kind == "portfolio_internal":
        if not is_same_domain(norm, state.root_url):
            return False, "not_same_domain_portfolio"
        return True, ""

    # inspiration_external — settings allowlist only (offered frontier may list more)
    host = _host_key(norm)
    if not host:
        return False, "invalid_host"

    allowed = allowed_inspiration_hosts(settings)
    if not allowed:
        return False, "inspiration_allowlist_empty"

    if host in allowed:
        return True, ""

    # Allow subdomains of listed hosts (e.g. www. prefix already stripped)
    for a in allowed:
        if host == a or host.endswith("." + a):
            return True, ""

    return False, "host_not_in_inspiration_allowlist"


def cap_planner_urls_for_playwright(
    urls: list[str],
    *,
    max_pages: int,
) -> list[str]:
    """Enforce max pages per graph-run batch."""
    if max_pages <= 0:
        return []
    return urls[:max_pages]
