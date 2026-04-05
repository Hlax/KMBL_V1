"""URL evidence tiers for auditable crawl progression.

Categorises how a URL was identified as "used" during a graph run,
from strongest evidence (verified fetch) to weakest (frontier fallback).

Each tier carries a numeric priority — lower is stronger.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

_log = logging.getLogger(__name__)

# Maximum URLs that can be credited from raw-payload heuristic per run.
MAX_RAW_PAYLOAD_CREDITS_PER_RUN = 3


class EvidenceTier:
    """Evidence strength constants — lower value = stronger evidence."""

    VERIFIED_FETCH = 1
    SELECTED_BY_PLANNER = 2
    BUILD_SPEC_STRUCTURED = 3
    RAW_PAYLOAD_TEXT = 4
    FRONTIER_FALLBACK = 5

    _LABELS: dict[int, str] = {
        1: "verified_fetch",
        2: "selected_by_planner",
        3: "build_spec_structured",
        4: "raw_payload_text",
        5: "frontier_fallback",
    }

    @classmethod
    def label(cls, tier: int) -> str:
        return cls._LABELS.get(tier, f"unknown_{tier}")


@dataclass
class UrlEvidence:
    """A single URL with its evidence tier and source metadata."""

    url: str
    tier: int
    source: str  # human-readable provenance tag

    def __repr__(self) -> str:
        return f"UrlEvidence({self.url!r}, tier={self.tier}, source={self.source!r})"


@dataclass
class CrawlAdvancementReport:
    """Full observability report for a single crawl-advance cycle.

    Captures every URL category so a run can be inspected after the fact.
    """

    offered_urls: list[str] = field(default_factory=list)
    mentioned_urls: list[str] = field(default_factory=list)
    selected_urls: list[str] = field(default_factory=list)
    verified_urls: list[str] = field(default_factory=list)
    final_visited: list[UrlEvidence] = field(default_factory=list)
    evidence_tier_used: str = ""
    raw_payload_credits: int = 0
    domain_filtered_count: int = 0
    capped_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise for event payload / logging."""
        return {
            "offered_urls": self.offered_urls,
            "mentioned_urls": self.mentioned_urls,
            "selected_urls": self.selected_urls,
            "verified_urls": self.verified_urls,
            "final_visited": [
                {"url": e.url, "tier": e.tier, "source": e.source}
                for e in self.final_visited
            ],
            "evidence_tier_used": self.evidence_tier_used,
            "raw_payload_credits": self.raw_payload_credits,
            "domain_filtered_count": self.domain_filtered_count,
            "capped_count": self.capped_count,
        }


# ---------------------------------------------------------------------------
# Guards: same-domain / allowed-source filtering
# ---------------------------------------------------------------------------


def filter_same_domain_or_allowed(
    urls: list[str],
    root_url: str,
    allowed_domains: set[str] | None = None,
) -> tuple[list[str], int]:
    """Return URLs that share the root domain or are in *allowed_domains*.

    Returns (filtered_list, dropped_count).
    """
    root_host = _extract_host(root_url)
    allowed = allowed_domains or set()

    kept: list[str] = []
    dropped = 0
    seen: set[str] = set()
    for u in urls:
        if u in seen:
            dropped += 1
            continue
        seen.add(u)
        host = _extract_host(u)
        if host == root_host or host in allowed:
            kept.append(u)
        else:
            dropped += 1
    return kept, dropped


def cap_urls(urls: list[str], max_count: int) -> tuple[list[str], int]:
    """Return at most *max_count* URLs.  Returns (capped_list, excess_count)."""
    if len(urls) <= max_count:
        return urls, 0
    return urls[:max_count], len(urls) - max_count


# ---------------------------------------------------------------------------
# Evidence resolution: pick the best available evidence
# ---------------------------------------------------------------------------


def resolve_evidence(
    *,
    offered_urls: list[str],
    build_spec_urls: list[str],
    raw_payload_urls: list[str],
    root_url: str,
    allowed_domains: set[str] | None = None,
) -> CrawlAdvancementReport:
    """Resolve which URLs to mark visited based on tiered evidence.

    Priority order (strongest first):
      1. verified_fetch    — not implemented yet; placeholder
      2. selected_by_planner — not implemented yet; placeholder
      3. build_spec_structured — URLs from structured build_spec ∩ offered
      4. raw_payload_text  — URLs from raw payload ∩ offered (capped + domain-filtered)
      5. frontier_fallback — first offered URL

    Returns a full CrawlAdvancementReport for observability.
    """
    report = CrawlAdvancementReport(
        offered_urls=list(offered_urls),
        mentioned_urls=list(dict.fromkeys(build_spec_urls + raw_payload_urls)),
    )
    offered_set = set(offered_urls)

    # --- Tier 3: build_spec structured ---
    bs_matched = [u for u in build_spec_urls if u in offered_set]
    if bs_matched:
        evidence = [
            UrlEvidence(url=u, tier=EvidenceTier.BUILD_SPEC_STRUCTURED, source="build_spec_structured")
            for u in bs_matched
        ]
        report.final_visited = evidence
        report.selected_urls = bs_matched
        report.evidence_tier_used = EvidenceTier.label(EvidenceTier.BUILD_SPEC_STRUCTURED)
        return report

    # --- Tier 4: raw payload text (with guards) ---
    rp_matched = [u for u in raw_payload_urls if u in offered_set]
    if rp_matched:
        # Guard 1: same-domain or allowed
        filtered, domain_dropped = filter_same_domain_or_allowed(
            rp_matched, root_url, allowed_domains,
        )
        report.domain_filtered_count = domain_dropped

        # Guard 2: cap per run
        capped, excess = cap_urls(filtered, MAX_RAW_PAYLOAD_CREDITS_PER_RUN)
        report.capped_count = excess
        report.raw_payload_credits = len(capped)

        if capped:
            evidence = [
                UrlEvidence(url=u, tier=EvidenceTier.RAW_PAYLOAD_TEXT, source="raw_payload_text")
                for u in capped
            ]
            report.final_visited = evidence
            report.selected_urls = capped
            report.evidence_tier_used = EvidenceTier.label(EvidenceTier.RAW_PAYLOAD_TEXT)
            return report

    # --- Tier 5: frontier fallback ---
    if offered_urls:
        fallback = offered_urls[0]
        report.final_visited = [
            UrlEvidence(url=fallback, tier=EvidenceTier.FRONTIER_FALLBACK, source="frontier_fallback"),
        ]
        report.selected_urls = [fallback]
        report.evidence_tier_used = EvidenceTier.label(EvidenceTier.FRONTIER_FALLBACK)
    return report


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_host(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
        return host.removeprefix("www.")
    except Exception:
        return ""
