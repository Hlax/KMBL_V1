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

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.domain import CrawlStateRecord
from kmbl_orchestrator.identity.crawl_ranking import (
    internal_coverage_ready_for_inspiration,
    rank_summaries_for_planner,
    sort_internal_frontier,
)
from kmbl_orchestrator.identity.crawl_url_policy import filter_frontier_candidate_urls
from kmbl_orchestrator.identity.site_key import canonical_site_key
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
    # Technical / interactive reference (three.js ecosystem) — second-phase inspiration
    "https://threejs.org/docs/",
    "https://threejs.org/examples/",
    "https://github.com/mrdoob/three.js",
]


def get_or_create_crawl_state(
    repo: "Repository",
    identity_id: UUID,
    root_url: str,
) -> CrawlStateRecord:
    """Load merged crawl state, or link to existing site memory, or create fresh site + identity rows."""
    repo.ensure_site_backing_for_identity(identity_id)
    nu = normalize_url(root_url)
    sk = canonical_site_key(nu)

    existing = repo.get_crawl_state(identity_id)
    if existing is not None:
        if normalize_url(existing.root_url) != nu:
            _log.info(
                "crawl_state root_url changed for identity_id=%s: %s → %s, re-seeding",
                identity_id,
                existing.root_url,
                root_url,
            )
            return _create_fresh_state(repo, identity_id, root_url)
        return existing

    site = repo.get_site_crawl_state(sk)
    if site is not None:
        link = CrawlStateRecord(
            identity_id=identity_id,
            root_url=nu,
            site_key=sk,
            crawl_phase="identity_grounding",
            has_reused_site_memory=True,
            visited_urls=[],
            unvisited_urls=[],
            page_summaries={},
            visit_provenance={},
            crawl_status="in_progress",
            external_inspiration_urls=[],
            total_pages_crawled=0,
            last_crawled_at=None,
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        repo.upsert_crawl_state(link)
        _log.info(
            "crawl_state linked identity_id=%s to existing site_key=%s",
            identity_id,
            sk,
        )
        merged = repo.get_crawl_state(identity_id)
        assert merged is not None
        return merged

    return _create_fresh_state(repo, identity_id, root_url)


def _create_fresh_state(
    repo: "Repository",
    identity_id: UUID,
    root_url: str,
) -> CrawlStateRecord:
    """Create site frontier + identity link (merged view)."""
    normalized_root = normalize_url(root_url)
    sk = canonical_site_key(normalized_root)
    now = datetime.now(timezone.utc).isoformat()
    state = CrawlStateRecord(
        identity_id=identity_id,
        root_url=normalized_root,
        site_key=sk,
        crawl_phase="identity_grounding",
        has_reused_site_memory=False,
        visited_urls=[],
        unvisited_urls=[normalized_root],
        page_summaries={},
        visit_provenance={},
        crawl_status="in_progress",
        external_inspiration_urls=[],
        total_pages_crawled=0,
        last_crawled_at=None,
        created_at=now,
        updated_at=now,
    )
    repo.upsert_crawl_state(state)
    out = repo.get_crawl_state(identity_id)
    assert out is not None
    _log.info("crawl_state created for identity_id=%s site_key=%s", identity_id, sk)
    return out


def record_page_visit(
    repo: "Repository",
    identity_id: UUID,
    url: str,
    *,
    summary: str = "",
    design_signals: list[str] | None = None,
    tone_keywords: list[str] | None = None,
    discovered_links: list[str] | None = None,
    provenance_source: str = "",
    provenance_tier: int = 0,
    run_id: str = "",
    reference_sketch: dict[str, Any] | None = None,
) -> CrawlStateRecord:
    """Mark a URL as visited and record page-level data.

    Args:
        url: The URL that was crawled (will be normalized).
        summary: One-line summary of the page content.
        design_signals: Visual/design signals extracted from the page.
        tone_keywords: Tone/mood keywords from the page.
        reference_sketch: Optional compact dict from Playwright wrapper (taste/layout/motion notes) —
            not raw HTML; capped by caller.
        discovered_links: Raw href values found on the page (will be resolved + filtered).
        provenance_source: Why this URL was marked visited (e.g. ``build_spec_structured``).
        provenance_tier: Numeric evidence tier (lower = stronger).
        run_id: Graph run ID that triggered this visit.

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

    # Store page summary (origin distinguishes portfolio vs inspiration for planner shaping)
    summaries = dict(state.page_summaries)
    origin: str = "portfolio" if is_same_domain(normalized, state.root_url) else "inspiration"
    if len(summaries) < _MAX_PAGE_SUMMARIES:
        row: dict[str, Any] = {
            "summary": (summary or "")[:_MAX_SUMMARY_LENGTH],
            "design_signals": (design_signals or [])[:_MAX_DESIGN_SIGNALS_PER_PAGE],
            "tone_keywords": (tone_keywords or [])[:_MAX_TONE_KEYWORDS_PER_PAGE],
            "crawled_at": now,
            "origin": origin,
        }
        if reference_sketch and isinstance(reference_sketch, dict):
            row["reference_sketch"] = reference_sketch
        summaries[normalized] = row

    # Store visit provenance (why was this URL marked visited?)
    provenance = dict(state.visit_provenance)
    if provenance_source:
        provenance[normalized] = {
            "source": provenance_source,
            "tier": provenance_tier,
            "run_id": run_id,
            "recorded_at": now,
        }

    # Process discovered links: resolve, drop low-value paths, then enqueue internal frontier
    if discovered_links:
        visited_set = set(visited)
        unvisited_set = set(unvisited)
        resolved_list: list[str] = []
        for href in discovered_links:
            resolved = resolve_url(href, normalized)
            if resolved is None:
                continue
            resolved_list.append(resolved)
        filtered_internal = filter_frontier_candidate_urls(
            resolved_list,
            root_url=state.root_url,
        )
        for resolved in filtered_internal:
            if resolved in visited_set or resolved in unvisited_set:
                continue
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

    extracted = list(state.extracted_urls)
    if normalized not in extracted and (
        (summary or "").strip()
        or (design_signals or [])
        or (tone_keywords or [])
    ):
        extracted.append(normalized)

    digest = hashlib.sha256(
        json.dumps(summaries, sort_keys=True, default=str).encode("utf-8", errors="replace")
    ).hexdigest()[:16]

    updated = state.model_copy(
        update={
            "visited_urls": visited,
            "unvisited_urls": unvisited,
            "page_summaries": summaries,
            "visit_provenance": provenance,
            "crawl_status": crawl_status,
            "total_pages_crawled": state.total_pages_crawled + 1,
            "last_crawled_at": now,
            "extracted_urls": extracted,
            "extracted_fact_digest": digest,
            "updated_at": now,
        }
    )
    repo.upsert_crawl_state(updated)
    _maybe_promote_to_inspiration_phase(repo, identity_id)
    merged = repo.get_crawl_state(identity_id)
    return merged if merged is not None else updated


def _maybe_promote_to_inspiration_phase(repo: "Repository", identity_id: UUID) -> None:
    """When internal coverage is sufficient, advance phase and seed allowlisted inspiration URLs."""
    settings = get_settings()
    st = repo.get_crawl_state(identity_id)
    if st is None or st.crawl_phase != "identity_grounding":
        return
    if not internal_coverage_ready_for_inspiration(
        root_url=st.root_url,
        unvisited_urls=st.unvisited_urls,
        page_summaries=st.page_summaries,
        min_strong_internal_pages=settings.kmbl_crawl_min_strong_internal_pages,
    ):
        return
    seed_external_inspiration(repo, identity_id, urls=None)
    fresh = repo.get_crawl_state(identity_id)
    if fresh is None:
        return
    promoted = fresh.model_copy(
        update={
            "crawl_phase": "inspiration_expansion",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    repo.upsert_crawl_state(promoted)


def get_next_urls_to_crawl(
    state: CrawlStateRecord,
    *,
    batch_size: int = 5,
) -> list[str]:
    """Return the next batch of URLs to crawl from the frontier.

    Identity grounding phase: same-domain URLs only, ranked by heuristic score.
    Inspiration phase: remaining internal URLs first, then allowlisted external seeds.
    """
    if state.crawl_phase == "identity_grounding":
        internal = [u for u in state.unvisited_urls if is_same_domain(u, state.root_url)]
        ranked = sort_internal_frontier(internal, root_url=state.root_url)
        return ranked[:batch_size]

    internal = [u for u in state.unvisited_urls if is_same_domain(u, state.root_url)]
    if internal:
        ranked = sort_internal_frontier(internal, root_url=state.root_url)
        return ranked[:batch_size]

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


# ---------------------------------------------------------------------------
# Planner selected_urls contract — included in every crawl_context payload
# ---------------------------------------------------------------------------

_SELECTED_URLS_CONTRACT: dict[str, Any] = {
    "instruction": (
        "You MUST return `selected_urls` in your output — a list of the URLs "
        "from `next_urls_to_crawl` that you actually consulted or whose content "
        "influenced your plan.  Rules:\n"
        "1. ONLY include URLs from `next_urls_to_crawl` or explicitly allowed "
        "external inspiration URLs. Do NOT invent URLs.\n"
        "2. Prefer the exact absolute URL as listed in `next_urls_to_crawl`.\n"
        "3. Relative paths (e.g. /about, ./contact) are accepted but absolute "
        "URLs are preferred.\n"
        "4. If you did not consult any frontier URL, return `selected_urls: []`.\n"
        "5. Do NOT omit the field — always include it."
    ),
    "examples": [
        {
            "scenario": "Planner consulted two offered pages",
            "next_urls_to_crawl": [
                "https://acme.com/about",
                "https://acme.com/work",
                "https://acme.com/contact",
            ],
            "correct_output": {
                "selected_urls": [
                    "https://acme.com/about",
                    "https://acme.com/work",
                ],
            },
        },
        {
            "scenario": "Planner used a page but only had the relative path",
            "next_urls_to_crawl": [
                "https://acme.com/projects/alpha",
                "https://acme.com/blog",
            ],
            "correct_output": {
                "selected_urls": ["/projects/alpha"],
            },
            "note": "Relative paths are resolved against root_url automatically.",
        },
        {
            "scenario": "Planner did not use any frontier URL",
            "next_urls_to_crawl": [
                "https://acme.com/old-page",
            ],
            "correct_output": {
                "selected_urls": [],
            },
        },
    ],
    "forbidden": (
        "Do NOT include URLs that are not in `next_urls_to_crawl` or "
        "the allowed external inspiration set.  Invented URLs are discarded "
        "by the orchestrator."
    ),
}


def _has_rendered_evidence(data: dict[str, Any]) -> bool:
    """True when the page summary carries Playwright-rendered ``reference_sketch``."""
    rs = data.get("reference_sketch")
    return isinstance(rs, dict) and bool(rs)


def build_crawl_context_for_planner(
    state: CrawlStateRecord | None,
) -> dict[str, Any]:
    """Build a compact crawl context payload for the planner.

    This gives the planner enough information to decide what to crawl next
    and whether to expand to external inspiration sites.

    **Separation of concerns (planner-facing):**
    - Identity *seed* truth lives in ``identity_brief`` / ``structured_identity`` (not repeated here).
    - This payload carries **working crawl memory** only: frontier, counts, and short summaries
      split into portfolio vs inspiration. Operational visit logs are never included.
    """
    if state is None:
        return {"crawl_available": False}

    next_urls = get_next_urls_to_crawl(state, batch_size=5)
    all_summaries = list(state.page_summaries.items())

    def _item(url: str, data: dict[str, Any]) -> dict[str, Any]:
        origin = data.get("origin")
        if origin not in ("portfolio", "inspiration"):
            origin = (
                "portfolio" if is_same_domain(url, state.root_url) else "inspiration"
            )
        rs = data.get("reference_sketch")
        has_rendered = _has_rendered_evidence(data)
        out = {
            "url": url,
            "summary": data.get("summary", ""),
            "design_signals": data.get("design_signals", []),
            "tone_keywords": data.get("tone_keywords", []),
            "origin": origin,
            "has_rendered_evidence": has_rendered,
        }
        if has_rendered:
            out["reference_sketch"] = rs
        return out

    portfolio_items: list[dict[str, Any]] = []
    inspiration_items: list[dict[str, Any]] = []
    for url, data in all_summaries:
        item = _item(url, data)
        if item["origin"] == "portfolio":
            portfolio_items.append(item)
        else:
            inspiration_items.append(item)

    # Most recent first within each bucket (page_summaries insertion order ≈ crawl order)
    recent_portfolio = portfolio_items[-3:]
    recent_inspiration = inspiration_items[-3:]

    # Back-compat: short combined list for older prompts (capped, tagged)
    recent_combined: list[dict[str, Any]] = (recent_portfolio + recent_inspiration)[-5:]

    # Detect whether any page summaries contain real fetched data
    has_real_data = any(
        bool(data.get("design_signals")) or bool(data.get("tone_keywords"))
        for data in state.page_summaries.values()
    )

    has_prior = (state.total_pages_crawled or 0) > 0 or len(state.visited_urls) > 0

    settings = get_settings()
    top_identity_pages = rank_summaries_for_planner(
        portfolio_items,
        root_url=state.root_url,
        origin="portfolio",
        limit=5,
    )
    top_inspiration_pages: list[dict[str, Any]] = []
    if state.crawl_phase == "inspiration_expansion":
        top_inspiration_pages = rank_summaries_for_planner(
            inspiration_items,
            root_url=state.root_url,
            origin="inspiration",
            limit=5,
        )

    stale = False
    days_since_site_update: int | None = None
    if state.site_memory_updated_at:
        try:
            raw_ts = state.site_memory_updated_at.replace("Z", "+00:00")
            ts = datetime.fromisoformat(raw_ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - ts
            days_since_site_update = max(0, delta.days)
            stale = days_since_site_update >= settings.kmbl_site_memory_stale_days
        except Exception:
            stale = False

    # Count pages with Playwright-rendered evidence (materially richer grounding)
    rendered_evidence_count = sum(
        1 for data in state.page_summaries.values()
        if isinstance(data, dict) and _has_rendered_evidence(data)
    )

    return {
        "crawl_available": True,
        "crawl_phase": state.crawl_phase,
        "crawl_status": state.crawl_status,
        "root_url": state.root_url,
        "has_site_memory": bool(state.site_key),
        "has_reused_shared_site_crawl": state.has_reused_site_memory,
        "total_pages_crawled": state.total_pages_crawled,
        "visited_count": len(state.visited_urls),
        "unvisited_count": len(state.unvisited_urls),
        "next_urls_to_crawl": next_urls,
        "recent_page_summaries": recent_combined,
        "recent_portfolio_summaries": recent_portfolio,
        "recent_inspiration_summaries": recent_inspiration,
        "top_identity_pages": top_identity_pages,
        "top_inspiration_pages": top_inspiration_pages,
        "external_inspiration_available": bool(state.external_inspiration_urls),
        "is_exhausted": state.crawl_status == "exhausted",
        "grounding_available": has_real_data,
        "rendered_evidence_count": rendered_evidence_count,
        "resume": {
            "has_prior_crawl_memory": has_prior,
            "frontier_internal_urls_remaining": len(
                [u for u in state.unvisited_urls if is_same_domain(u, state.root_url)]
            ),
        },
        "freshness": {
            "site_memory_stale": stale,
            "days_since_site_memory_update": days_since_site_update,
            "stale_after_days": settings.kmbl_site_memory_stale_days,
        },
        "memory_contract": (
            "identity_seed: use identity_brief + structured_identity for durable profile; "
            "working_crawl: frontier + summaries below; operational visit logs are not shown here."
        ),
        "evidence_contract": (
            "Identity pages (portfolio / same-domain) are truth-bearing for this brand. "
            "Inspiration pages are reference-only and must not override identity truth. "
            f"Current phase: {state.crawl_phase}."
        ),
        # Planner instructions for selected_urls contract:
        "selected_urls_contract": _SELECTED_URLS_CONTRACT,
        "extracted_url_count": len(state.extracted_urls),
        "rejected_url_count": len(state.rejected_urls),
        "extracted_fact_digest": state.extracted_fact_digest or "",
        "extracted_urls_sample": list(state.extracted_urls)[-24:],
        "grounded_reference_urls": list(state.page_summaries.keys())[-48:],
    }
