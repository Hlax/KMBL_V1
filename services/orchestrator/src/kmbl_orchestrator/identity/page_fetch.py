"""Lightweight HTML page fetcher for grounded crawl exploration.

Fetches real page content using httpx and extracts:
- Page title
- Meta description
- Internal links (for frontier discovery)
- Basic design signals (color-related, font, layout keywords)
- Tone keywords from meta/title content

This is intentionally minimal — no JavaScript rendering, no full DOM parsing.
Uses only stdlib html.parser + httpx (both already in deps).
"""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

_log = logging.getLogger(__name__)

# Limits
_FETCH_TIMEOUT = 8.0  # seconds
_MAX_CONTENT_BYTES = 512 * 1024  # 512KB — skip huge pages
_MAX_LINKS = 100  # max links to extract per page
_MAX_TITLE_LEN = 200
_MAX_DESCRIPTION_LEN = 500

# Design signal keywords (found in class names, inline styles, meta)
_DESIGN_KEYWORDS = frozenset({
    "grid", "flex", "flexbox", "masonry", "carousel", "slider",
    "hero", "parallax", "fullscreen", "minimal", "dark-mode",
    "light-mode", "gradient", "glassmorphism", "neumorphism",
    "responsive", "mobile-first", "sidebar", "navbar", "footer",
    "card", "modal", "overlay", "animation", "transition",
    "webgl", "canvas", "three", "threejs", "gsap", "lottie",
})

# Tone keywords from meta descriptions / titles
_TONE_KEYWORDS = frozenset({
    "creative", "professional", "minimal", "bold", "elegant",
    "modern", "vintage", "playful", "serious", "artistic",
    "innovative", "clean", "luxurious", "sophisticated", "dynamic",
    "interactive", "immersive", "experimental", "editorial",
})


class _PageDataExtractor(HTMLParser):
    """Minimal HTML parser that extracts title, meta, links, and design signals."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.title = ""
        self.description = ""
        self.links: list[str] = []
        self.design_signals: set[str] = set()
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k: v for k, v in attrs if v is not None}

        if tag == "title":
            self._in_title = True
            self._title_parts = []

        elif tag == "meta":
            name = (attr_dict.get("name") or "").lower()
            content = attr_dict.get("content") or ""
            if name == "description" and content:
                self.description = content[:_MAX_DESCRIPTION_LEN]
            elif name in ("keywords", "theme-color"):
                self._extract_design_from_text(content)

        elif tag == "a":
            href = attr_dict.get("href")
            if href and len(self.links) < _MAX_LINKS:
                resolved = urljoin(self.base_url, href)
                if resolved.startswith(("http://", "https://")):
                    self.links.append(resolved)

        elif tag == "link":
            rel = (attr_dict.get("rel") or "").lower()
            href = attr_dict.get("href") or ""
            if "stylesheet" in rel and href:
                # Note external CSS frameworks as design signals
                lower_href = href.lower()
                if "tailwind" in lower_href:
                    self.design_signals.add("tailwindcss")
                elif "bootstrap" in lower_href:
                    self.design_signals.add("bootstrap")
                elif "bulma" in lower_href:
                    self.design_signals.add("bulma")

        elif tag == "script":
            src = (attr_dict.get("src") or "").lower()
            if "three" in src:
                self.design_signals.add("threejs")
            elif "gsap" in src:
                self.design_signals.add("gsap")
            elif "lottie" in src:
                self.design_signals.add("lottie")

        # Extract design signals from class names
        class_val = attr_dict.get("class") or ""
        if class_val:
            self._extract_design_from_text(class_val)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._in_title:
            self._in_title = False
            self.title = " ".join(self._title_parts).strip()[:_MAX_TITLE_LEN]

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)

    def _extract_design_from_text(self, text: str) -> None:
        lower = text.lower()
        for kw in _DESIGN_KEYWORDS:
            if kw in lower:
                self.design_signals.add(kw)

    def error(self, message: str) -> None:
        pass  # Ignore parse errors — we're best-effort


def fetch_page_data(
    url: str,
    *,
    timeout: float = _FETCH_TIMEOUT,
) -> dict[str, Any] | None:
    """Fetch a page and extract structured data.

    Returns None on any failure (network, timeout, non-HTML, too large).

    Returns dict with:
        - url: the fetched URL
        - title: page <title>
        - description: meta description
        - links: list of absolute href URLs found
        - design_signals: list of design-related keywords found
        - tone_keywords: list of tone keywords found in title/description
        - status_code: HTTP status code
    """
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=1),
        ) as client:
            resp = client.get(
                url,
                headers={
                    "User-Agent": "KMBL-Crawler/1.0 (design-exploration)",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )

        # Skip non-success or non-HTML
        if resp.status_code >= 400:
            _log.debug("page_fetch url=%s status=%d — skipping", url, resp.status_code)
            return None

        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type and "xhtml" not in content_type:
            _log.debug("page_fetch url=%s content_type=%s — not HTML", url, content_type)
            return None

        # Size check
        body = resp.text
        if len(body) > _MAX_CONTENT_BYTES:
            body = body[:_MAX_CONTENT_BYTES]

        parser = _PageDataExtractor(str(resp.url))
        try:
            parser.feed(body)
        except Exception:
            pass  # best-effort parsing

        # Extract tone keywords from title + description
        combined_text = f"{parser.title} {parser.description}".lower()
        tone = [kw for kw in _TONE_KEYWORDS if kw in combined_text]

        return {
            "url": str(resp.url),
            "title": parser.title,
            "description": parser.description,
            "links": parser.links,
            "design_signals": sorted(parser.design_signals),
            "tone_keywords": tone,
            "status_code": resp.status_code,
        }

    except httpx.TimeoutException:
        _log.debug("page_fetch url=%s — timeout", url)
        return None
    except Exception as exc:
        _log.debug("page_fetch url=%s — error: %s", url, str(exc)[:200])
        return None


def extract_urls_from_text(text: str) -> list[str]:
    """Extract HTTP(S) URLs from arbitrary text (e.g. planner output).

    Uses a simple regex — not perfect but good enough for grounding.
    """
    if not isinstance(text, str):
        return []
    pattern = r'https?://[^\s<>"\')\]},]+'
    return list(dict.fromkeys(re.findall(pattern, text)))  # deduplicated, order-preserved


def extract_urls_from_build_spec(build_spec: dict[str, Any]) -> list[str]:
    """Extract URLs referenced in a planner build_spec dict.

    Walks the dict looking for string values containing URLs.
    Returns deduplicated list of URLs found.
    """
    if not isinstance(build_spec, dict):
        return []

    urls: list[str] = []
    seen: set[str] = set()

    def _walk(obj: Any) -> None:
        if isinstance(obj, str):
            for u in extract_urls_from_text(obj):
                if u not in seen:
                    seen.add(u)
                    urls.append(u)
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(build_spec)
    return urls


def filter_crawl_urls(
    candidate_urls: list[str],
    offered_urls: list[str],
) -> list[str]:
    """Return only URLs from candidates that were in the offered crawl batch.

    This ensures we only mark URLs as "visited" if they were actually
    available in the crawl context AND referenced by the planner.
    """
    offered_set = set(offered_urls)
    return [u for u in candidate_urls if u in offered_set]
