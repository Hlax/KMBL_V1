"""Selected URL grounding tags for planner build_spec."""

from __future__ import annotations

from kmbl_orchestrator.identity.crawl_frontier_tags import annotate_selected_urls_grounding


def test_annotate_selected_urls_grounding() -> None:
    bs = {"selected_urls": ["https://ex.com/a", "https://ex.com/b"]}
    cc = {
        "visited_count": 2,
        "grounded_reference_urls": ["https://ex.com/a"],
        "next_urls_to_crawl": ["https://ex.com/b"],
    }
    meta = annotate_selected_urls_grounding(bs, cc)
    assert meta is not None
    assert meta["selected_url_count"] == 2
    assert bs["_kmbl_selected_url_grounding_meta"]["visited_url_count"] == 2
    g = {x["url"]: x["grounding"] for x in bs["_kmbl_selected_urls_grounding"]}
    assert g["https://ex.com/a"] == "grounded"
    assert g["https://ex.com/b"] == "pending_frontier"
