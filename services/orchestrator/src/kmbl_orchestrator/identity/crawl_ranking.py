"""Deterministic page URL scoring for frontier ordering and coverage gating."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from kmbl_orchestrator.identity.crawl_url_policy import is_low_value_crawl_url
from kmbl_orchestrator.identity.url_normalize import is_same_domain

# High-value path hints for identity/design grounding (boost score)
_HIGH_VALUE_PATH_RE: tuple[re.Pattern[str], ...] = (
    re.compile(r"/(work|works|portfolio|projects?|case-stud|gallery|about|studio|services)(/|$)", re.I),
    re.compile(r"/(design|creative|labs)(/|$)", re.I),
)


def score_url_for_internal_crawl(url: str, *, root_url: str) -> float:
    """Higher = crawl sooner for identity grounding. Range roughly 0..1."""
    if not is_same_domain(url, root_url):
        return 0.0
    if is_low_value_crawl_url(url):
        return 0.05
    try:
        path = urlparse(url).path or "/"
    except Exception:
        return 0.2
    s = 0.35
    for pat in _HIGH_VALUE_PATH_RE:
        if pat.search(path):
            s = min(1.0, s + 0.35)
            break
    if path in ("/", ""):
        s = max(s, 0.9)
    return round(s, 3)


def sort_internal_frontier(urls: list[str], *, root_url: str) -> list[str]:
    """Descending by score; stable for ties."""
    scored = [(score_url_for_internal_crawl(u, root_url=root_url), i, u) for i, u in enumerate(urls)]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [u for _, __, u in scored]


def summary_strength(data: dict[str, Any]) -> float:
    """Proxy for 'strong' internal page from stored summary.

    Pages with a ``reference_sketch`` (Playwright-rendered evidence) receive a
    boost because they carry materially richer design/layout signals than
    lightweight HTTP-only fetches.
    """
    sig = len(data.get("design_signals") or [])
    tone = len(data.get("tone_keywords") or [])
    summ = len((data.get("summary") or "").strip())
    base = 0.15 * sig + 0.1 * tone + min(0.4, summ / 400.0)
    # Playwright-rendered evidence boost
    rs = data.get("reference_sketch")
    if isinstance(rs, dict) and rs:
        base += 0.25
    return min(1.0, base)


def count_strong_internal_pages(
    page_summaries: dict[str, Any],
    *,
    root_url: str,
    min_strength: float = 0.35,
) -> int:
    n = 0
    for url, data in page_summaries.items():
        if not isinstance(data, dict):
            continue
        if not is_same_domain(url, root_url):
            continue
        if summary_strength(data) >= min_strength:
            n += 1
    return n


def internal_coverage_ready_for_inspiration(
    *,
    root_url: str,
    unvisited_urls: list[str],
    page_summaries: dict[str, Any],
    min_strong_internal_pages: int = 2,
) -> bool:
    """True when internal identity site has enough signal and no high-priority internal URLs remain."""
    strong = count_strong_internal_pages(page_summaries, root_url=root_url)
    internal_uv = [u for u in unvisited_urls if is_same_domain(u, root_url)]
    high_value_left = [
        u
        for u in internal_uv
        if score_url_for_internal_crawl(u, root_url=root_url) >= 0.3
    ]
    if high_value_left:
        return False
    if not internal_uv:
        return True
    if strong >= min_strong_internal_pages:
        return True
    return False


def rank_summaries_for_planner(
    items: list[dict[str, Any]],
    *,
    root_url: str,
    origin: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Attach crawl_rank score and sort descending."""
    out: list[tuple[float, int, dict[str, Any]]] = []
    for i, it in enumerate(items):
        url = str(it.get("url", ""))
        base = score_url_for_internal_crawl(url, root_url=root_url) if origin == "portfolio" else 0.4
        st = summary_strength(it) if isinstance(it, dict) else 0.0
        score = base * 0.5 + st * 0.5
        row = dict(it)
        row["crawl_rank"] = round(score, 3)
        out.append((score, i, row))
    out.sort(key=lambda x: (-x[0], x[1]))
    return [x[2] for x in out[:limit]]
