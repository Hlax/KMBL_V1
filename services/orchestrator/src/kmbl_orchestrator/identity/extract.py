"""
Website identity extraction — fetch a URL and produce an IdentitySeed.

Uses httpx (already a project dependency) for fetching and stdlib html.parser
for lightweight HTML extraction. No BeautifulSoup or heavy scraping dependencies.

Supports multi-page crawling to build richer identity signals.
"""

from __future__ import annotations

import html.parser
import logging
import re
import time
from urllib.parse import urljoin, urlparse

import httpx

from kmbl_orchestrator.identity.seed import IdentitySeed

_log = logging.getLogger(__name__)

_FETCH_TIMEOUT = 15.0
_MAX_BODY_BYTES = 512 * 1024
_USER_AGENT = "KMBL-Orchestrator/identity-extract"

# Pages worth crawling for richer identity
_PRIORITY_SLUGS = {"about", "work", "portfolio", "projects", "services", "team", "contact", "bio", "story"}
_MAX_PAGES = 5  # Max pages to crawl (including landing)
_MAX_CRAWL_SECONDS = 30.0  # Total time budget for deep crawl

# Storage limits — keep data compact
_MAX_TONE_KEYWORDS = 8
_MAX_AESTHETIC_KEYWORDS = 6
_MAX_PALETTE_HINTS = 8
_MAX_PROJECT_EVIDENCE = 10
_MAX_IMAGE_REFS = 16
_MAX_HEADINGS = 15
_MAX_BODY_TEXT_CHARS = 2000  # For profile summary extraction


class _SignalParser(html.parser.HTMLParser):
    """Single-pass HTML parser that collects identity signals."""

    def __init__(self) -> None:
        super().__init__()
        self.title: str | None = None
        self.meta_description: str | None = None
        self.meta_keywords: list[str] = []
        self.og: dict[str, str] = {}
        self.headings: list[str] = []
        self.image_srcs: list[str] = []
        self.link_texts: list[str] = []
        self.link_hrefs: list[str] = []  # For discovering internal pages
        self.body_text_chunks: list[str] = []

        self._in_title = False
        self._in_heading = False
        self._in_a = False
        self._in_body = False
        self._in_script = False
        self._in_style = False
        self._heading_buf: list[str] = []
        self._title_buf: list[str] = []
        self._link_buf: list[str] = []
        self._current_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        ad = {k.lower(): (v or "") for k, v in attrs}

        if t == "title":
            self._in_title = True
            self._title_buf = []
        elif t in ("h1", "h2", "h3"):
            self._in_heading = True
            self._heading_buf = []
        elif t == "a":
            self._in_a = True
            self._link_buf = []
            self._current_href = ad.get("href")
        elif t == "body":
            self._in_body = True
        elif t == "script":
            self._in_script = True
        elif t == "style":
            self._in_style = True
        elif t == "meta":
            name = ad.get("name", "").lower()
            prop = ad.get("property", "").lower()
            content = ad.get("content", "")
            if name == "description" and content:
                self.meta_description = content.strip()
            elif name == "keywords" and content:
                self.meta_keywords = [k.strip() for k in content.split(",") if k.strip()]
            elif prop.startswith("og:") and content:
                self.og[prop] = content.strip()
        elif t == "img":
            src = ad.get("src", "")
            if src and not src.startswith("data:"):
                self.image_srcs.append(src)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "title":
            self._in_title = False
            text = "".join(self._title_buf).strip()
            if text:
                self.title = text
        elif t in ("h1", "h2", "h3"):
            self._in_heading = False
            text = "".join(self._heading_buf).strip()
            if text and len(self.headings) < 20:
                self.headings.append(text)
        elif t == "a":
            self._in_a = False
            text = "".join(self._link_buf).strip()
            if text and len(self.link_texts) < 30:
                self.link_texts.append(text)
            if self._current_href and len(self.link_hrefs) < 50:
                self.link_hrefs.append(self._current_href)
            self._current_href = None
        elif t == "script":
            self._in_script = False
        elif t == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_buf.append(data)
        if self._in_heading:
            self._heading_buf.append(data)
        if self._in_a:
            self._link_buf.append(data)
        if self._in_body and not self._in_script and not self._in_style:
            stripped = data.strip()
            if stripped and len(self.body_text_chunks) < 200:
                self.body_text_chunks.append(stripped)


_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}")
_TONE_WORDS = {
    "professional", "creative", "minimal", "bold", "elegant", "playful",
    "modern", "classic", "clean", "vibrant", "warm", "cool", "dark",
    "light", "friendly", "serious", "fun", "corporate", "personal",
    "artistic", "technical", "innovative",
}


def _infer_tone_keywords(text: str, headings: list[str]) -> list[str]:
    combined = (text + " " + " ".join(headings)).lower()
    found = [w for w in _TONE_WORDS if w in combined]
    return sorted(set(found))[:6]


def _infer_aesthetic_from_headings(headings: list[str]) -> list[str]:
    keywords: list[str] = []
    for h in headings[:10]:
        lower = h.lower()
        if any(w in lower for w in ("portfolio", "work", "projects", "gallery")):
            keywords.append("portfolio")
        if any(w in lower for w in ("about", "bio", "story")):
            keywords.append("personal")
        if any(w in lower for w in ("service", "offering", "solution")):
            keywords.append("services")
        if any(w in lower for w in ("contact", "reach", "connect")):
            keywords.append("contact-focused")
    return sorted(set(keywords))[:4]


def _extract_palette_hints(body_text: str) -> list[str]:
    colors = _COLOR_RE.findall(body_text)
    return list(dict.fromkeys(colors))[:6]


def _resolve_image_urls(base_url: str, raw_srcs: list[str]) -> list[str]:
    resolved: list[str] = []
    for src in raw_srcs[:12]:
        try:
            full = urljoin(base_url, src)
            if full.startswith(("http://", "https://")):
                resolved.append(full)
        except Exception:
            continue
    return resolved


def _infer_project_evidence(headings: list[str], link_texts: list[str]) -> list[str]:
    evidence: list[str] = []
    project_words = {"project", "work", "portfolio", "case study", "client", "built", "designed"}
    for text in headings + link_texts:
        lower = text.lower()
        if any(w in lower for w in project_words) and len(text) < 120:
            evidence.append(text)
        if len(evidence) >= 6:
            break
    return evidence


def _infer_display_name(title: str | None, og: dict[str, str]) -> str | None:
    og_title = og.get("og:title")
    og_name = og.get("og:site_name")
    if og_name:
        return og_name.strip()[:80]
    if og_title:
        parts = re.split(r"\s*[|–—-]\s*", og_title)
        if parts:
            return parts[0].strip()[:80]
    if title:
        parts = re.split(r"\s*[|–—-]\s*", title)
        if parts:
            return parts[0].strip()[:80]
    return None


def _infer_role_or_title(headings: list[str], body_text: str) -> str | None:
    role_patterns = [
        r"(?:i(?:'m| am)\s+(?:a\s+)?)([\w\s&/,]+?)(?:\.|,|$)",
        r"([\w\s]+(?:designer|developer|engineer|consultant|founder|artist|photographer|writer|creator|architect|strategist))",
    ]
    search_text = " ".join(headings[:5]) + " " + body_text[:500]
    for pattern in role_patterns:
        m = re.search(pattern, search_text, re.IGNORECASE)
        if m:
            return m.group(1).strip()[:80]
    return None


def _infer_short_bio(
    meta_desc: str | None, og: dict[str, str], body_chunks: list[str]
) -> str | None:
    og_desc = og.get("og:description")
    if og_desc and len(og_desc) > 20:
        return og_desc[:200]
    if meta_desc and len(meta_desc) > 20:
        return meta_desc[:200]
    for chunk in body_chunks[:10]:
        if len(chunk) > 40:
            return chunk[:200]
    return None


def _discover_priority_links(base_url: str, hrefs: list[str]) -> list[str]:
    """Find internal links to priority pages (about, work, portfolio, etc.)."""
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower()
    discovered: list[str] = []
    seen_slugs: set[str] = set()

    for href in hrefs:
        if not href:
            continue
        # Resolve relative URLs
        try:
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
        except Exception:
            continue

        # Must be same domain (internal link)
        if parsed.netloc.lower() != base_domain:
            continue

        # Check if path matches priority slugs
        path_parts = [p.lower() for p in parsed.path.strip("/").split("/") if p]
        if not path_parts:
            continue

        slug = path_parts[0]
        if slug in _PRIORITY_SLUGS and slug not in seen_slugs:
            seen_slugs.add(slug)
            discovered.append(full_url)

        if len(discovered) >= _MAX_PAGES - 1:  # -1 because we already have landing
            break

    return discovered


def _merge_seeds(primary: IdentitySeed, secondary_pages: list[IdentitySeed]) -> IdentitySeed:
    """Merge signals from multiple pages into enriched primary seed."""
    if not secondary_pages:
        return primary

    # Aggregate lists
    all_tone = list(primary.tone_keywords or [])
    all_aesthetic = list(primary.aesthetic_keywords or [])
    all_palette = list(primary.palette_hints or [])
    all_project = list(primary.project_evidence or [])
    all_images = list(primary.image_refs or [])
    all_headings = list(primary.headings or [])
    crawled_pages: list[str] = [primary.source_url]

    for page in secondary_pages:
        if page.tone_keywords:
            all_tone.extend(page.tone_keywords)
        if page.aesthetic_keywords:
            all_aesthetic.extend(page.aesthetic_keywords)
        if page.palette_hints:
            all_palette.extend(page.palette_hints)
        if page.project_evidence:
            all_project.extend(page.project_evidence)
        if page.image_refs:
            all_images.extend(page.image_refs)
        if page.headings:
            all_headings.extend(page.headings)
        crawled_pages.append(page.source_url)

        # Use secondary bio/role if primary is missing
        if not primary.short_bio and page.short_bio:
            primary = IdentitySeed(
                **{**primary.__dict__, "short_bio": page.short_bio}
            )
        if not primary.role_or_title and page.role_or_title:
            primary = IdentitySeed(
                **{**primary.__dict__, "role_or_title": page.role_or_title}
            )

    # Dedupe and limit
    notes = list(primary.extraction_notes or [])
    notes.append(f"Multi-page crawl: {len(crawled_pages)} pages")

    return IdentitySeed(
        source_url=primary.source_url,
        display_name=primary.display_name,
        role_or_title=primary.role_or_title,
        short_bio=primary.short_bio[:200] if primary.short_bio else None,
        tone_keywords=sorted(set(all_tone))[:_MAX_TONE_KEYWORDS],
        aesthetic_keywords=sorted(set(all_aesthetic))[:_MAX_AESTHETIC_KEYWORDS],
        palette_hints=list(dict.fromkeys(all_palette))[:_MAX_PALETTE_HINTS],
        layout_hints=primary.layout_hints[:4] if primary.layout_hints else [],
        project_evidence=list(dict.fromkeys(all_project))[:_MAX_PROJECT_EVIDENCE],
        image_refs=list(dict.fromkeys(all_images))[:_MAX_IMAGE_REFS],
        headings=list(dict.fromkeys(all_headings))[:_MAX_HEADINGS],
        meta_description=primary.meta_description[:200] if primary.meta_description else None,
        extraction_notes=notes[:10],  # Keep notes compact
        confidence=min(1.0, primary.confidence + 0.1 * len(secondary_pages)),
        crawled_pages=crawled_pages,
    )


def _extract_single_page(url: str, client: httpx.Client) -> tuple[IdentitySeed, _SignalParser | None]:
    """Fetch and parse a single page. Returns (seed, parser) or (partial_seed, None)."""
    notes: list[str] = []

    try:
        resp = client.get(url)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        notes.append(f"HTTP {e.response.status_code} fetching URL")
        _log.warning("identity extract HTTP error for %s: %s", url, e)
        return IdentitySeed(source_url=url, extraction_notes=notes, confidence=0.1), None
    except httpx.HTTPError as e:
        notes.append(f"Connection error: {type(e).__name__}")
        _log.warning("identity extract connection error for %s: %s", url, e)
        return IdentitySeed(source_url=url, extraction_notes=notes, confidence=0.0), None

    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type.lower():
        notes.append(f"Content-Type is {content_type}; expected HTML")

    body = resp.text[:_MAX_BODY_BYTES]

    parser = _SignalParser()
    try:
        parser.feed(body)
    except Exception as e:
        notes.append(f"HTML parse warning: {type(e).__name__}")

    body_text = " ".join(parser.body_text_chunks)
    display_name = _infer_display_name(parser.title, parser.og)
    role_or_title = _infer_role_or_title(parser.headings, body_text)
    short_bio = _infer_short_bio(parser.meta_description, parser.og, parser.body_text_chunks)
    tone_keywords = _infer_tone_keywords(body_text, parser.headings)
    aesthetic_keywords = _infer_aesthetic_from_headings(parser.headings)
    palette_hints = _extract_palette_hints(body)
    image_refs = _resolve_image_urls(url, parser.image_srcs)
    project_evidence = _infer_project_evidence(parser.headings, parser.link_texts)

    signal_count = sum([
        bool(display_name),
        bool(role_or_title),
        bool(short_bio),
        len(tone_keywords) > 0,
        len(parser.headings) > 0,
        len(image_refs) > 0,
    ])
    confidence = min(1.0, signal_count / 6.0)
    confidence = round(confidence, 2)

    seed = IdentitySeed(
        source_url=url,
        display_name=display_name,
        role_or_title=role_or_title,
        short_bio=short_bio,
        tone_keywords=tone_keywords,
        aesthetic_keywords=aesthetic_keywords,
        palette_hints=palette_hints,
        layout_hints=aesthetic_keywords[:2],
        project_evidence=project_evidence,
        image_refs=image_refs,
        headings=parser.headings[:10],
        meta_description=parser.meta_description,
        extraction_notes=notes,
        confidence=confidence,
    )
    return seed, parser


def extract_identity_from_url(url: str, *, deep_crawl: bool = False) -> IdentitySeed:
    """
    Fetch a website URL and extract identity signals into an IdentitySeed.

    Args:
        url: The website URL to extract identity from.
        deep_crawl: If True, crawl internal pages (about, work, portfolio, etc.)
                   to build richer identity signals.

    Returns a partial seed on fetch/parse failures (never raises for recoverable errors).
    Raises httpx.HTTPError only on complete connection failure.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return IdentitySeed(
            source_url=url,
            extraction_notes=["URL scheme not http(s); cannot fetch"],
            confidence=0.0,
        )

    with httpx.Client(
        timeout=_FETCH_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        # Extract landing page
        primary_seed, parser = _extract_single_page(url, client)

        if not deep_crawl or parser is None:
            return primary_seed

        # Discover and crawl priority internal pages
        priority_links = _discover_priority_links(url, parser.link_hrefs)
        if not priority_links:
            _log.info("deep_crawl: no priority pages found for %s", url)
            return primary_seed

        _log.info("deep_crawl: crawling %d additional pages for %s", len(priority_links), url)
        secondary_seeds: list[IdentitySeed] = []
        crawl_start = time.monotonic()

        for link in priority_links:
            # Respect time budget
            elapsed = time.monotonic() - crawl_start
            if elapsed >= _MAX_CRAWL_SECONDS:
                _log.info("deep_crawl: time budget exhausted (%.1fs), stopping", elapsed)
                break

            try:
                page_seed, _ = _extract_single_page(link, client)
                if page_seed.confidence > 0:
                    secondary_seeds.append(page_seed)
                    _log.debug("deep_crawl: extracted %s (confidence %.2f)", link, page_seed.confidence)
            except Exception as e:
                _log.warning("deep_crawl: failed to extract %s: %s", link, e)
                continue

        elapsed = time.monotonic() - crawl_start
        _log.info("deep_crawl: completed %d pages in %.1fs", len(secondary_seeds) + 1, elapsed)

        # Merge all signals
        return _merge_seeds(primary_seed, secondary_seeds)
