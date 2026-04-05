"""Durable multi-session crawl state manager.

Provides the core logic for:
- Initializing crawl state from a root URL
- Recording visited pages with summaries and design signals
- Discovering new internal links
- Detecting crawl exhaustion
- Transitioning to external inspiration sites after internal exhaustion
- Resuming crawl across sessions

All state is persisted via the Repository so it survives restarts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

from kmbl_orchestrator.domain import CrawlStateRecord
from kmbl_orchestrator.identity.url_normalize import (
    is_same_domain,
    normalize_url,
    resolve_url,
)

if TYPE_CHECKING:
    from kmbl_orchestrator.persistence.repository import Repository

_log = logging.getLogger(__name__)

# Max unvisited URLs to track per identity (prevent runaway growth)
_MAX_UNVISITED = 200
# Max visited URLs to retain in state (older entries are still counted but dropped from list)
_MAX_VISITED = 500
# Max page summaries to retain
_MAX_PAGE_SUMMARIES = 100
# Max characters for a page summary
_MAX_SUMMARY_LENGTH = 300
# Max design signals per page
_MAX_DESIGN_SIGNALS_PER_PAGE = 10
# Max tone keywords per page
_MAX_TONE_KEYWORDS_PER_PAGE = 8
# Max external inspiration URLs
_MAX_EXTERNAL_URLS = 20
# Default external inspiration URLs when internal crawl is exhausted
_DEFAULT_INSPIRATION_CATEGORIES = [
    "https://www.awwwards.com",
    "https://www.siteinspire.com",
    "https://dribbble.com",
]


def get_or_create_crawl_state(
    repo: "Repository",
    identity_id: UUID,
    root_url: str,
) -> CrawlStateRecord:
    """Load existing crawl state or create a fresh one seeded with the root URL.

    If a crawl state already exists for this identity, it is returned as-is
    (enabling cross-session resumption). Otherwise a new record is created
    with the root URL as the first unvisited entry.
    """
    existing = repo.get_crawl_state(identity_id)
    if existing is not None:
        # If root URL changed (user updated identity source), re-seed
        if normalize_url(existing.root_url) != normalize_url(root_url):
            _log.info(
                "crawl_state root_url changed for identity_id=%s: %s → %s, re-seeding",
                identity_id,
                existing.root_url,
                root_url,
            )
            return _create_fresh_state(repo, identity_id, root_url)
        return existing

    return _create_fresh_state(repo, identity_id, root_url)


def _create_fresh_state(
    repo: "Repository",
    identity_id: UUID,
    root_url: str,
) -> CrawlStateRecord:
    """Create and persist a fresh crawl state."""
    normalized_root = normalize_url(root_url)
    now = datetime.now(timezone.utc).isoformat()
    state = CrawlStateRecord(
        identity_id=identity_id,
        root_url=normalized_root,
        visited_urls=[],
        unvisited_urls=[normalized_root],
        page_summaries={},
        crawl_status="in_progress",
        external_inspiration_urls=[],
        total_pages_crawled=0,
        last_crawled_at=None,
        created_at=now,
        updated_at=now,
    )
    repo.upsert_crawl_state(state)
    _log.info("crawl_state created for identity_id=%s root=%s", identity_id, normalized_root)
    return state


def record_page_visit(
    repo: "Repository",
    identity_id: UUID,
    url: str,
    *,
    summary: str = "",
    design_signals: list[str] | None = None,
    tone_keywords: list[str] | None = None,
    discovered_links: list[str] | None = None,
) -> CrawlStateRecord:
    """Mark a URL as visited and record page-level data.

    Args:
        url: The URL that was crawled (will be normalized).
        summary: One-line summary of the page content.
        design_signals: Visual/design signals extracted from the page.
        tone_keywords: Tone/mood keywords from the page.
        discovered_links: Raw href values found on the page (will be resolved + filtered).

    Returns the updated crawl state.
    """
    state = repo.get_crawl_state(identity_id)
    if state is None:
        raise ValueError(f"No crawl state for identity_id={identity_id}; call get_or_create_crawl_state first")

    normalized = normalize_url(url)
    now = datetime.now(timezone.utc).isoformat()

    # Move from unvisited to visited
    visited = list(state.visited_urls)
    unvisited = list(state.unvisited_urls)
    if normalized not in visited:
        visited.append(normalized)
    if normalized in unvisited:
        unvisited.remove(normalized)

    # Store page summary
    summaries = dict(state.page_summaries)
    if len(summaries) < _MAX_PAGE_SUMMARIES:
        summaries[normalized] = {
            "summary": (summary or "")[:_MAX_SUMMARY_LENGTH],
            "design_signals": (design_signals or [])[:_MAX_DESIGN_SIGNALS_PER_PAGE],
            "tone_keywords": (tone_keywords or [])[:_MAX_TONE_KEYWORDS_PER_PAGE],
            "crawled_at": now,
        }

    # Process discovered links: resolve, normalize, filter internal, add to unvisited
    if discovered_links:
        visited_set = set(visited)
        unvisited_set = set(unvisited)
        for href in discovered_links:
            resolved = resolve_url(href, normalized)
            if resolved is None:
                continue
            if resolved in visited_set or resolved in unvisited_set:
                continue
            # Internal links are added to unvisited for future crawling
            if is_same_domain(resolved, state.root_url):
                if len(unvisited) < _MAX_UNVISITED:
                    unvisited.append(resolved)
                    unvisited_set.add(resolved)

    # Trim visited list (keep most recent)
    if len(visited) > _MAX_VISITED:
        visited = visited[-_MAX_VISITED:]

    # Determine crawl status
    crawl_status: str = state.crawl_status
    if not unvisited and crawl_status == "in_progress":
        crawl_status = "exhausted"
        _log.info(
            "crawl_state exhausted for identity_id=%s after %d pages",
            identity_id,
            len(visited),
        )

    updated = state.model_copy(
        update={
            "visited_urls": visited,
            "unvisited_urls": unvisited,
            "page_summaries": summaries,
            "crawl_status": crawl_status,
            "total_pages_crawled": state.total_pages_crawled + 1,
            "last_crawled_at": now,
            "updated_at": now,
        }
    )
    repo.upsert_crawl_state(updated)
    return updated


def get_next_urls_to_crawl(
    state: CrawlStateRecord,
    *,
    batch_size: int = 5,
) -> list[str]:
    """Return the next batch of URLs to crawl from the frontier.

    Prioritizes internal unvisited URLs. When internal crawl is exhausted,
    returns external inspiration URLs that haven't been visited yet.
    """
    if state.unvisited_urls:
        return state.unvisited_urls[:batch_size]

    # Internal crawl exhausted — try external inspiration
    if state.external_inspiration_urls:
        visited_set = set(state.visited_urls)
        external = [u for u in state.external_inspiration_urls if u not in visited_set]
        return external[:batch_size]

    return []


def seed_external_inspiration(
    repo: "Repository",
    identity_id: UUID,
    urls: list[str] | None = None,
) -> CrawlStateRecord:
    """Add external inspiration URLs after internal crawl exhaustion.

    Uses default inspiration sites if no URLs provided.
    """
    state = repo.get_crawl_state(identity_id)
    if state is None:
        raise ValueError(f"No crawl state for identity_id={identity_id}")

    source_urls = urls or list(_DEFAULT_INSPIRATION_CATEGORIES)
    normalized = [normalize_url(u) for u in source_urls]

    # Deduplicate against existing
    existing = set(state.external_inspiration_urls)
    new_urls = [u for u in normalized if u not in existing]

    all_external = list(state.external_inspiration_urls) + new_urls
    updated = state.model_copy(
        update={
            "external_inspiration_urls": all_external[:_MAX_EXTERNAL_URLS],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    repo.upsert_crawl_state(updated)
    _log.info(
        "crawl_state external_inspiration seeded for identity_id=%s: %d urls",
        identity_id,
        len(new_urls),
    )
    return updated


def build_crawl_context_for_planner(
    state: CrawlStateRecord | None,
) -> dict[str, Any]:
    """Build a compact crawl context payload for the planner.

    This gives the planner enough information to decide what to crawl next
    and whether to expand to external inspiration sites.
    """
    if state is None:
        return {"crawl_available": False}

    next_urls = get_next_urls_to_crawl(state, batch_size=5)
    recent_summaries: list[dict[str, Any]] = []
    # Show the 5 most recently crawled page summaries
    all_summaries = list(state.page_summaries.items())
    for url, data in all_summaries[-5:]:
        recent_summaries.append({
            "url": url,
            "summary": data.get("summary", ""),
            "design_signals": data.get("design_signals", []),
        })

    return {
        "crawl_available": True,
        "crawl_status": state.crawl_status,
        "root_url": state.root_url,
        "total_pages_crawled": state.total_pages_crawled,
        "visited_count": len(state.visited_urls),
        "unvisited_count": len(state.unvisited_urls),
        "next_urls_to_crawl": next_urls,
        "recent_page_summaries": recent_summaries,
        "external_inspiration_available": bool(state.external_inspiration_urls),
        "is_exhausted": state.crawl_status == "exhausted",
    }
