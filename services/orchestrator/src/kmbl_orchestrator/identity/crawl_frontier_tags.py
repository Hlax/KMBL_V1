"""Planner-facing tags for ``selected_urls`` vs crawl frontier (grounded vs pending vs stale)."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.identity.url_normalize import normalize_url


def annotate_selected_urls_grounding(
    build_spec: dict[str, Any],
    crawl_context: dict[str, Any],
) -> dict[str, Any] | None:
    """Mutates ``build_spec`` with ``_kmbl_selected_urls_grounding`` and returns telemetry meta."""
    su = build_spec.get("selected_urls")
    if not isinstance(su, list) or not su:
        return None

    grounded: set[str] = set()
    for u in crawl_context.get("grounded_reference_urls") or []:
        if isinstance(u, str) and u.strip():
            grounded.add(normalize_url(u.strip()))
    for u in crawl_context.get("extracted_urls_sample") or []:
        if isinstance(u, str) and u.strip():
            grounded.add(normalize_url(u.strip()))

    pending: set[str] = set()
    for u in crawl_context.get("next_urls_to_crawl") or []:
        if isinstance(u, str) and u.strip():
            pending.add(normalize_url(u.strip()))

    out: list[dict[str, Any]] = []
    for raw_u in su[:48]:
        if not isinstance(raw_u, str) or not raw_u.strip():
            continue
        nu = normalize_url(raw_u.strip())
        if nu in grounded:
            g = "grounded"
        elif nu in pending:
            g = "pending_frontier"
        else:
            g = "reused_stale"
        out.append({"url": raw_u, "grounding": g})

    visited_n = int(crawl_context.get("visited_count") or 0)
    newly = sum(1 for x in out if x["grounding"] in ("grounded", "pending_frontier"))
    reused = sum(1 for x in out if x["grounding"] == "reused_stale")

    build_spec["_kmbl_selected_urls_grounding"] = out
    meta = {
        "selected_url_count": len(out),
        "newly_grounded_url_count": newly,
        "reused_url_count": reused,
        "visited_url_count": visited_n,
    }
    build_spec["_kmbl_selected_url_grounding_meta"] = meta
    return meta
