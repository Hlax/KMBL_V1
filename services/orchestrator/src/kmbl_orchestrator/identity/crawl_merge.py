"""Merge identity-level crawl link rows with site-level shared frontier state."""

from __future__ import annotations

from datetime import datetime, timezone

from kmbl_orchestrator.domain import CrawlStateRecord, SiteCrawlStateRecord


def site_record_from_merged_view(record: CrawlStateRecord) -> SiteCrawlStateRecord:
    """Build site row from a full merged :class:`CrawlStateRecord` (requires ``site_key``)."""
    sk = record.site_key
    if not sk:
        raise ValueError("site_record_from_merged_view requires site_key")
    now = datetime.now(timezone.utc).isoformat()
    return SiteCrawlStateRecord(
        site_key=sk,
        root_url=record.root_url,
        visited_urls=list(record.visited_urls),
        unvisited_urls=list(record.unvisited_urls),
        page_summaries=dict(record.page_summaries),
        visit_provenance=dict(record.visit_provenance),
        crawl_status=record.crawl_status,
        external_inspiration_urls=list(record.external_inspiration_urls),
        total_pages_crawled=record.total_pages_crawled,
        last_crawled_at=record.last_crawled_at,
        site_memory_updated_at=now,
        created_at=record.created_at,
        updated_at=now,
    )


def merge_identity_with_site(
    identity_row: CrawlStateRecord,
    site: SiteCrawlStateRecord | None,
) -> CrawlStateRecord:
    """Planner/runtime view: site frontier + identity phase / flags."""
    if site is None:
        return identity_row
    return CrawlStateRecord(
        identity_id=identity_row.identity_id,
        root_url=identity_row.root_url or site.root_url,
        site_key=identity_row.site_key,
        crawl_phase=identity_row.crawl_phase,
        has_reused_site_memory=identity_row.has_reused_site_memory,
        site_memory_updated_at=site.site_memory_updated_at,
        visited_urls=list(site.visited_urls),
        unvisited_urls=list(site.unvisited_urls),
        page_summaries=dict(site.page_summaries),
        visit_provenance=dict(site.visit_provenance),
        crawl_status=site.crawl_status,
        external_inspiration_urls=list(site.external_inspiration_urls),
        total_pages_crawled=site.total_pages_crawled,
        last_crawled_at=site.last_crawled_at,
        created_at=identity_row.created_at,
        updated_at=identity_row.updated_at,
    )


def slim_identity_row(base: CrawlStateRecord) -> CrawlStateRecord:
    """Persist identity-only columns when ``site_key`` is set (frontier lives on ``site_crawl_state``)."""
    return base.model_copy(
        update={
            "visited_urls": [],
            "unvisited_urls": [],
            "page_summaries": {},
            "visit_provenance": {},
            "external_inspiration_urls": [],
            "crawl_status": "in_progress",
            "total_pages_crawled": 0,
            "last_crawled_at": None,
        }
    )
