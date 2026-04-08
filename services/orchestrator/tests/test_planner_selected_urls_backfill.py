from __future__ import annotations

from kmbl_orchestrator.graph.nodes_pkg.planner import _backfill_selected_urls_from_crawl_context


def test_backfill_skips_when_selected_urls_already_present() -> None:
    raw = {
        "build_spec": {
            "selected_urls": ["https://example.com/about"],
            "identity_source": {"url": "https://example.com/"},
        }
    }
    cc = {"next_urls_to_crawl": ["https://example.com/about"]}

    meta = _backfill_selected_urls_from_crawl_context(
        raw,
        cc=cc,
        identity_url="https://example.com/",
        iteration_index=0,
    )

    assert meta is None
    assert raw["build_spec"]["selected_urls"] == ["https://example.com/about"]


def test_backfill_prefers_build_spec_referenced_urls() -> None:
    raw = {
        "build_spec": {
            "identity_source": {
                "crawled_pages": [
                    "https://example.com/about",
                    "https://example.com/work",
                ]
            }
        }
    }
    cc = {
        "next_urls_to_crawl": [
            "https://example.com/work",
            "https://example.com/contact",
        ]
    }

    meta = _backfill_selected_urls_from_crawl_context(
        raw,
        cc=cc,
        identity_url="https://example.com/",
        iteration_index=0,
    )

    assert meta == {
        "applied": True,
        "source": "build_spec_referenced",
        "count": 1,
    }
    assert raw["build_spec"]["selected_urls"] == ["https://example.com/work"]


def test_backfill_uses_frontier_default_when_no_referenced_match() -> None:
    raw = {
        "build_spec": {
            "title": "Demo",
            "steps": [],
        }
    }
    cc = {
        "next_urls_to_crawl": [
            "https://example.com/about",
            "https://example.com/work",
        ]
    }

    meta = _backfill_selected_urls_from_crawl_context(
        raw,
        cc=cc,
        identity_url="https://example.com/",
        iteration_index=0,
    )

    assert meta == {
        "applied": True,
        "source": "frontier_default",
        "count": 1,
    }
    assert raw["build_spec"]["selected_urls"] == ["https://example.com/about"]


def test_backfill_uses_grounded_reference_when_frontier_exhausted() -> None:
    raw = {
        "build_spec": {
            "title": "Grounded",
            "steps": [],
        }
    }
    cc = {
        "next_urls_to_crawl": [],
        "grounded_reference_urls": [
            "https://example.com/project/a",
            "https://example.com/about",
        ],
    }

    meta = _backfill_selected_urls_from_crawl_context(
        raw,
        cc=cc,
        identity_url="https://example.com/",
        iteration_index=0,
    )

    assert meta == {
        "applied": True,
        "source": "grounded_reference_default",
        "count": 1,
    }
    assert raw["build_spec"]["selected_urls"] == ["https://example.com/project/a"]
