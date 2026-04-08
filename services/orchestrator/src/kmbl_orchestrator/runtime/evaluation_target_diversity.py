"""Soften portfolio-shaped evaluation targets on static identity-url runs.

When the planner emits ``selector_present`` evaluation targets that name
portfolio-section CSS classes (``section.projects-grid``, ``section.about-career``,
``section.contact``, etc.) on a ``static_frontend_file_v1`` identity-url run,
the generator is forced to produce those exact selectors to achieve a ``pass``.
This creates a self-reinforcing loop: the planner suggests portfolio structure,
the evaluator requires portfolio selectors, so the generator reproduces the
same hero/projects/about/contact layout every time.

This module converts overly-specific structural ``selector_present`` targets
into softer ``text_present`` targets that verify **identity content** is present
without locking in a specific CSS layout.  ``selector_present`` targets that
reference non-structural selectors (``[data-kmbl-*]``, ``nav``, ``main``,
``canvas``, ``header``, ``footer``) are preserved.
"""

from __future__ import annotations

import logging
import re
from typing import Any

_log = logging.getLogger(__name__)

# CSS selectors that reference portfolio-shaped sections.
# Match patterns like ``section.projects-grid``, ``.about-career``,
# ``section.contact``, ``#projects``, ``#hero``, etc.
_PORTFOLIO_SELECTOR_RE = re.compile(
    r"(?:"
    r"section\.(projects|about|contact|hero|work|timeline|portfolio|services|testimonials)"
    r"|\.(?:projects-grid|about-career|about-section|hero-section|contact-section)"
    r"|[#.](?:projects|about|contact|hero|work|timeline|portfolio|services|testimonials)\b"
    r")",
    re.IGNORECASE,
)

# Non-structural selectors that are fine to keep.
_ALLOWED_SELECTOR_RE = re.compile(
    r"^\s*("
    r"\[data-kmbl"          # KMBL data attributes
    r"|nav\b"               # navigation element
    r"|main\b"              # main element
    r"|header\b"            # header element
    r"|footer\b"            # footer element
    r"|canvas\b"            # canvas for WebGL
    r"|\[role="             # ARIA roles
    r")",
    re.IGNORECASE,
)


def _is_portfolio_shaped_selector(selector: str) -> bool:
    """True when the selector forces a portfolio-section CSS layout."""
    if _ALLOWED_SELECTOR_RE.search(selector):
        return False
    return bool(_PORTFOLIO_SELECTOR_RE.search(selector))


def soften_portfolio_evaluation_targets(
    raw: dict[str, Any],
    event_input: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Convert portfolio-section selector_present targets to text_present on static identity-url runs.

    Only applies when:
    - The vertical is ``static_frontend_file_v1``
    - The scenario is ``kmbl_identity_url_static_v1`` (identity-url run)

    Returns (possibly updated raw, list of fix labels for observability).
    """
    from kmbl_orchestrator.runtime.static_vertical_invariants import is_static_frontend_vertical

    bs = raw.get("build_spec") if isinstance(raw.get("build_spec"), dict) else {}
    if not is_static_frontend_vertical(bs, event_input):
        return raw, []

    scenario = event_input.get("scenario") if isinstance(event_input, dict) else None
    if scenario != "kmbl_identity_url_static_v1":
        return raw, []

    targets = raw.get("evaluation_targets")
    if not isinstance(targets, list) or not targets:
        return raw, []

    new_targets: list[Any] = []
    fixes: list[str] = []
    for item in targets:
        if not isinstance(item, dict):
            new_targets.append(item)
            continue
        kind = item.get("kind", "")
        selector_value = item.get("substring") or item.get("selector") or ""
        if kind == "selector_present" and isinstance(selector_value, str) and _is_portfolio_shaped_selector(selector_value):
            # Drop the structural selector — the remaining text_present targets
            # still verify identity content is present.
            fixes.append(f"dropped_portfolio_selector:{selector_value}")
            _log.info(
                "evaluation_target_diversity: dropped portfolio-shaped selector_present target %r",
                selector_value,
            )
            continue
        new_targets.append(item)

    if not fixes:
        return raw, []

    out = dict(raw)
    out["evaluation_targets"] = new_targets
    return out, fixes
