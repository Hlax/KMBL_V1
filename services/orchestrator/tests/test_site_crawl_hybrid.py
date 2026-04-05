"""Site-level crawl memory reuse and phase gating."""

from __future__ import annotations

from uuid import uuid4

from kmbl_orchestrator.identity.crawl_state import (
    get_or_create_crawl_state,
    record_page_visit,
)
from kmbl_orchestrator.identity.site_key import canonical_site_key
from kmbl_orchestrator.persistence.repository import InMemoryRepository


def test_second_identity_reuses_site_frontier() -> None:
    repo = InMemoryRepository()
    i1 = uuid4()
    i2 = uuid4()
    get_or_create_crawl_state(repo, i1, "https://example.com")
    record_page_visit(
        repo,
        i1,
        "https://example.com/",
        discovered_links=["https://example.com/about"],
    )
    s2 = get_or_create_crawl_state(repo, i2, "https://example.com")
    assert s2.has_reused_site_memory is True
    assert canonical_site_key(s2.root_url) == "example.com"
    assert "https://example.com/about" in (s2.unvisited_urls + s2.visited_urls)


def test_identity_grounding_phase_before_inspiration() -> None:
    repo = InMemoryRepository()
    iid = uuid4()
    st = get_or_create_crawl_state(repo, iid, "https://acme.test")
    assert st.crawl_phase == "identity_grounding"
    assert st.site_key == "acme.test"
