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

from kmbl_orchestrator.identity.url_normalize import normalize_url

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
class FetchVerification:
    """Result of attempting to verify a URL via real fetch."""

    original_url: str
    resolved_url: str | None = None
    success: bool = False
    title: str = ""
    description: str = ""
    discovered_links: list[str] = field(default_factory=list)
    design_signals: list[str] = field(default_factory=list)
    tone_keywords: list[str] = field(default_factory=list)
    status_code: int | None = None
    failure_reason: str = ""


@dataclass
class CrawlAdvancementReport:
    """Full observability report for a single crawl-advance cycle.

    Captures every URL category so a run can be inspected after the fact.
    """

    offered_urls: list[str] = field(default_factory=list)
    mentioned_urls: list[str] = field(default_factory=list)
    planner_selected_urls: list[str] = field(default_factory=list)
    selected_urls: list[str] = field(default_factory=list)
    verified_urls: list[str] = field(default_factory=list)
    downgraded_urls: list[dict[str, str]] = field(default_factory=list)
    fetch_failures: list[dict[str, str]] = field(default_factory=list)
    final_visited: list[UrlEvidence] = field(default_factory=list)
    evidence_tier_used: str = ""
    raw_payload_credits: int = 0
    domain_filtered_count: int = 0
    capped_count: int = 0

    # --- Planner compliance metrics (FIX 2) ---
    planner_compliance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise for event payload / logging."""
        return {
            "offered_urls": self.offered_urls,
            "mentioned_urls": self.mentioned_urls,
            "planner_selected_urls": self.planner_selected_urls,
            "selected_urls": self.selected_urls,
            "verified_urls": self.verified_urls,
            "downgraded_urls": self.downgraded_urls,
            "fetch_failures": self.fetch_failures,
            "final_visited": [
                {"url": e.url, "tier": e.tier, "source": e.source}
                for e in self.final_visited
            ],
            "evidence_tier_used": self.evidence_tier_used,
            "raw_payload_credits": self.raw_payload_credits,
            "domain_filtered_count": self.domain_filtered_count,
            "capped_count": self.capped_count,
            "planner_compliance": self.planner_compliance,
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
# Normalized URL matching (FIX 3)
# ---------------------------------------------------------------------------


def _normalize_url_set(urls: list[str]) -> dict[str, str]:
    """Build normalized→original mapping for a list of URLs.

    Returns dict[normalized_url, original_url].  First occurrence wins.
    """
    mapping: dict[str, str] = {}
    for u in urls:
        normed = normalize_url(u)
        if normed not in mapping:
            mapping[normed] = u
    return mapping


def _match_against_offered(
    candidate_urls: list[str],
    offered_norm_map: dict[str, str],
) -> list[str]:
    """Return offered URLs that any candidate URL normalizes to.

    Uses canonical normalization so trailing-slash / fragment / tracking-param
    differences do not cause false negatives.
    Returns the *offered* form of each matched URL (for consistent provenance).
    """
    matched: list[str] = []
    seen: set[str] = set()
    for u in candidate_urls:
        normed = normalize_url(u)
        offered_original = offered_norm_map.get(normed)
        if offered_original is not None and offered_original not in seen:
            seen.add(offered_original)
            matched.append(offered_original)
    return matched


# ---------------------------------------------------------------------------
# Verified fetch support (FIX 2)
# ---------------------------------------------------------------------------


def verify_url_fetch(url: str, *, timeout: float = 5.0) -> FetchVerification:
    """Perform a real HTTP fetch and return structured verification result.

    This is the *only* path that can produce ``verified_fetch`` evidence.
    On any failure the result has ``success=False`` with a reason string.
    """
    from kmbl_orchestrator.identity.page_fetch import fetch_page_data

    try:
        page_data = fetch_page_data(url, timeout=timeout)
    except Exception as exc:
        return FetchVerification(
            original_url=url,
            success=False,
            failure_reason=f"fetch exception: {str(exc)[:200]}",
        )

    if page_data is None:
        return FetchVerification(
            original_url=url,
            success=False,
            failure_reason="fetch returned None (timeout/non-HTML/error)",
        )

    resolved = page_data.get("url") or url
    # Confirm the resolved URL maps to the same logical page after normalization
    if normalize_url(resolved) != normalize_url(url):
        # Redirect to a different page — still valid if same domain
        if _extract_host(resolved) != _extract_host(url):
            return FetchVerification(
                original_url=url,
                resolved_url=resolved,
                success=False,
                failure_reason=f"redirect to different domain: {resolved}",
            )

    return FetchVerification(
        original_url=url,
        resolved_url=resolved,
        success=True,
        title=page_data.get("title", ""),
        description=page_data.get("description", ""),
        discovered_links=page_data.get("links", []),
        design_signals=page_data.get("design_signals", []),
        tone_keywords=page_data.get("tone_keywords", []),
        status_code=page_data.get("status_code"),
    )


# ---------------------------------------------------------------------------
# Evidence resolution: pick the best available evidence
# ---------------------------------------------------------------------------


def resolve_evidence(
    *,
    offered_urls: list[str],
    planner_selected_urls: list[str] | None = None,
    build_spec_urls: list[str],
    raw_payload_urls: list[str],
    root_url: str,
    allowed_domains: set[str] | None = None,
) -> CrawlAdvancementReport:
    """Resolve which URLs to mark visited based on tiered evidence.

    Priority order (strongest first):
      1. verified_fetch       — assigned post-resolution by caller via ``try_upgrade_to_verified``
      2. selected_by_planner  — explicit ``selected_urls`` from planner output ∩ offered
      3. build_spec_structured — URLs from structured build_spec ∩ offered
      4. raw_payload_text     — URLs from raw payload ∩ offered (capped + domain-filtered)
      5. frontier_fallback    — first offered URL

    Returns a full CrawlAdvancementReport for observability.
    """
    report = CrawlAdvancementReport(
        offered_urls=list(offered_urls),
        mentioned_urls=list(dict.fromkeys(build_spec_urls + raw_payload_urls)),
        planner_selected_urls=list(planner_selected_urls or []),
    )

    # Build a normalized lookup for offered URLs (FIX 3)
    offered_norm = _normalize_url_set(offered_urls)

    # --- Tier 2: planner-selected URLs (FIX 1) ---
    if planner_selected_urls:
        ps_matched = _match_against_offered(planner_selected_urls, offered_norm)
        if ps_matched:
            evidence = [
                UrlEvidence(url=u, tier=EvidenceTier.SELECTED_BY_PLANNER, source="selected_by_planner")
                for u in ps_matched
            ]
            report.final_visited = evidence
            report.selected_urls = ps_matched
            report.evidence_tier_used = EvidenceTier.label(EvidenceTier.SELECTED_BY_PLANNER)
            return report

    # --- Tier 3: build_spec structured ---
    bs_matched = _match_against_offered(build_spec_urls, offered_norm)
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
    rp_matched = _match_against_offered(raw_payload_urls, offered_norm)
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


def try_upgrade_to_verified(
    evidence: UrlEvidence,
    report: CrawlAdvancementReport,
    *,
    timeout: float = 5.0,
) -> tuple[UrlEvidence, FetchVerification]:
    """Attempt to upgrade a piece of evidence to ``verified_fetch``.

    Performs a real HTTP fetch.  On success the evidence tier is upgraded
    to ``VERIFIED_FETCH`` and the URL is added to ``report.verified_urls``.
    On failure the original tier is kept and the failure is recorded in the
    report's ``downgraded_urls`` and ``fetch_failures`` lists.

    Returns (possibly-upgraded UrlEvidence, FetchVerification).
    """
    vf = verify_url_fetch(evidence.url, timeout=timeout)
    if vf.success:
        upgraded = UrlEvidence(
            url=evidence.url,
            tier=EvidenceTier.VERIFIED_FETCH,
            source="verified_fetch",
        )
        report.verified_urls.append(evidence.url)
        return upgraded, vf

    # Fetch failed — keep original tier, record the downgrade
    report.downgraded_urls.append({
        "url": evidence.url,
        "kept_tier": EvidenceTier.label(evidence.tier),
        "reason": vf.failure_reason,
    })
    report.fetch_failures.append({
        "url": evidence.url,
        "reason": vf.failure_reason,
    })
    return evidence, vf


# ---------------------------------------------------------------------------
# Planner selected URL extraction (FIX 1)
# ---------------------------------------------------------------------------


def extract_planner_selected_urls(
    build_spec: dict[str, Any],
    *,
    root_url: str | None = None,
) -> list[str]:
    """Extract explicitly selected URLs from planner build_spec output.

    The planner may declare which crawl URLs it intentionally chose via:
    - ``build_spec.selected_urls`` (list of URL strings)
    - ``build_spec.crawl_actions.selected_urls`` (nested path)

    When *root_url* is provided, relative paths (e.g. ``/about``,
    ``work/project-a``, ``./contact``) are resolved against it before
    filtering.  Only ``http`` / ``https`` results are kept.

    Returns deduplicated list of URLs found, or empty list.
    """
    if not isinstance(build_spec, dict):
        return []

    urls: list[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, str) or not item.strip():
                    continue
                resolved = _resolve_planner_url(item, root_url)
                if resolved is not None and resolved not in seen:
                    seen.add(resolved)
                    urls.append(resolved)

    # Top-level: build_spec.selected_urls
    _add(build_spec.get("selected_urls"))

    # Nested: build_spec.crawl_actions.selected_urls
    crawl_actions = build_spec.get("crawl_actions")
    if isinstance(crawl_actions, dict):
        _add(crawl_actions.get("selected_urls"))

    return urls


def match_planner_selections_to_offered(
    planner_selected_urls: list[str],
    offered_urls: list[str],
) -> list[str]:
    """Return offered-frontier URL strings that match planner selections (normalized intersection)."""
    if not planner_selected_urls:
        return []
    return _match_against_offered(planner_selected_urls, _normalize_url_set(offered_urls))


def _resolve_planner_url(raw: str, root_url: str | None) -> str | None:
    """Resolve a planner-emitted URL string to an absolute http(s) URL.

    * Already-absolute http(s) URLs are returned as-is.
    * Relative paths (``/about``, ``./contact``, ``work/x``) are resolved
      against *root_url* when provided.
    * Fragment-only, clearly invalid, or non-http results return ``None``.
    """
    raw = raw.strip()
    if not raw:
        return None

    # Already absolute http(s)
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw

    # Reject clearly non-http schemes using urlparse for reliable detection
    parsed = urlparse(raw)
    if parsed.scheme and parsed.scheme not in ("http", "https"):
        # e.g. ftp://..., mailto:..., javascript:..., data:...
        return None

    # Fragment-only (e.g. "#section") — not a page URL
    if raw.startswith("#"):
        return None

    # Resolve relative against root_url
    if root_url:
        from kmbl_orchestrator.identity.url_normalize import resolve_url
        return resolve_url(raw, root_url)

    # No root_url to resolve against — relative path cannot be converted
    return None


# ---------------------------------------------------------------------------
# Planner compliance validation + consistency check (FIX 2 + FIX 3)
# ---------------------------------------------------------------------------


def compute_planner_compliance(
    *,
    offered_urls: list[str],
    raw_planner_selected: list[str],
    resolved_planner_selected: list[str],
    matched_count: int,
    build_spec_urls: list[str],
    evidence_tier_used: str,
    root_url: str,
) -> dict[str, Any]:
    """Compute planner compliance metrics for observability.

    Returns a dict suitable for inclusion in the CrawlAdvancementReport
    and event payloads.  Fields:

    * ``selected_urls_present`` — planner returned a non-empty selected_urls
    * ``selected_urls_count`` — raw count before normalization/resolution
    * ``selected_urls_valid_count`` — count after resolution (http/https only)
    * ``selected_urls_matched_count`` — count that matched offered frontier
    * ``selected_urls_rejected_count`` — valid but not in offered set
    * ``tier2_evidence_fired`` — whether tier-2 (selected_by_planner) was used
    * ``degraded_to_tier`` — which tier was actually used (if not tier-2)
    * ``frontier_was_offered`` — whether offered_urls was non-empty
    * ``omitted_despite_frontier`` — planner had URLs to pick from but didn't
    * ``selected_urls_consistent_with_output`` — at least one selected URL also
      appears in build_spec structured output (lightweight confidence signal)
    """
    frontier_offered = bool(offered_urls)
    present = bool(raw_planner_selected)
    raw_count = len(raw_planner_selected)
    valid_count = len(resolved_planner_selected)
    rejected_count = valid_count - matched_count
    tier2_fired = evidence_tier_used == EvidenceTier.label(EvidenceTier.SELECTED_BY_PLANNER)

    # --- FIX 3: consistency check ---
    # Compare selected_urls against build_spec_urls using normalization.
    consistent = False
    if resolved_planner_selected and build_spec_urls:
        sel_norm = {normalize_url(u) for u in resolved_planner_selected}
        bs_norm = {normalize_url(u) for u in build_spec_urls}
        consistent = bool(sel_norm & bs_norm)

    return {
        "selected_urls_present": present,
        "selected_urls_count": raw_count,
        "selected_urls_valid_count": valid_count,
        "selected_urls_matched_count": matched_count,
        "selected_urls_rejected_count": rejected_count,
        "tier2_evidence_fired": tier2_fired,
        "crawl_evidence_tier_used": evidence_tier_used,
        "degraded_to_tier": evidence_tier_used if not tier2_fired else None,
        "frontier_was_offered": frontier_offered,
        "omitted_despite_frontier": frontier_offered and not present,
        "selected_urls_consistent_with_output": consistent,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_host(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
        return host.removeprefix("www.")
    except Exception:
        return ""
