"""Tests for evaluation_target_diversity — portfolio selector softening."""

from __future__ import annotations

import pytest

from kmbl_orchestrator.runtime.evaluation_target_diversity import (
    _is_portfolio_shaped_selector,
    soften_portfolio_evaluation_targets,
)


# ---------------------------------------------------------------------------
# Unit: _is_portfolio_shaped_selector
# ---------------------------------------------------------------------------

class TestIsPortfolioShapedSelector:
    @pytest.mark.parametrize("selector", [
        "section.projects-grid",
        "section.about-career",
        "section.contact",
        "section.hero",
        "section.work",
        "section.timeline",
        "section.portfolio",
        "section.services",
        "section.testimonials",
        ".projects-grid",
        ".about-career",
        ".about-section",
        ".hero-section",
        ".contact-section",
        "#projects",
        "#about",
        "#contact",
        "#hero",
        "#work",
    ])
    def test_detects_portfolio_selectors(self, selector: str) -> None:
        assert _is_portfolio_shaped_selector(selector) is True

    @pytest.mark.parametrize("selector", [
        "[data-kmbl-scene]",
        "[data-kmbl-cool-lane]",
        "nav",
        "nav.primary",
        "main",
        "header",
        "footer",
        "canvas",
        '[role="main"]',
        ".custom-widget",
        ".gallery-item",
        "div.mosaic",
    ])
    def test_preserves_non_portfolio_selectors(self, selector: str) -> None:
        assert _is_portfolio_shaped_selector(selector) is False


# ---------------------------------------------------------------------------
# Integration: soften_portfolio_evaluation_targets
# ---------------------------------------------------------------------------

class TestSoftenPortfolioEvaluationTargets:
    def _identity_url_event_input(self) -> dict:
        return {
            "scenario": "kmbl_identity_url_static_v1",
            "constraints": {
                "canonical_vertical": "static_frontend_file_v1",
            },
        }

    def _build_spec_static(self) -> dict:
        return {"type": "static_frontend_file_v1"}

    def test_drops_portfolio_selectors_on_identity_url_static(self) -> None:
        raw = {
            "build_spec": self._build_spec_static(),
            "evaluation_targets": [
                {"kind": "text_present", "substring": "Harvey Lacsina"},
                {"kind": "text_present", "substring": "creative producer & director"},
                {"kind": "selector_present", "substring": "section.projects-grid"},
                {"kind": "selector_present", "substring": "section.about-career"},
                {"kind": "selector_present", "substring": "section.contact"},
            ],
        }
        ei = self._identity_url_event_input()
        out, fixes = soften_portfolio_evaluation_targets(raw, ei)
        assert len(fixes) == 3
        assert len(out["evaluation_targets"]) == 2  # only text_present targets remain
        kinds = [t["kind"] for t in out["evaluation_targets"]]
        assert all(k == "text_present" for k in kinds)

    def test_preserves_non_portfolio_selectors(self) -> None:
        raw = {
            "build_spec": self._build_spec_static(),
            "evaluation_targets": [
                {"kind": "text_present", "substring": "Harvey Lacsina"},
                {"kind": "selector_present", "substring": "nav"},
                {"kind": "selector_present", "substring": "[data-kmbl-scene]"},
                {"kind": "selector_present", "substring": "section.projects-grid"},
            ],
        }
        ei = self._identity_url_event_input()
        out, fixes = soften_portfolio_evaluation_targets(raw, ei)
        assert len(fixes) == 1
        assert len(out["evaluation_targets"]) == 3

    def test_noop_when_no_portfolio_selectors(self) -> None:
        raw = {
            "build_spec": self._build_spec_static(),
            "evaluation_targets": [
                {"kind": "text_present", "substring": "Harvey Lacsina"},
                {"kind": "selector_present", "substring": "nav"},
            ],
        }
        ei = self._identity_url_event_input()
        out, fixes = soften_portfolio_evaluation_targets(raw, ei)
        assert fixes == []
        assert out is raw  # no mutation, same object

    def test_noop_when_not_identity_url_scenario(self) -> None:
        raw = {
            "build_spec": self._build_spec_static(),
            "evaluation_targets": [
                {"kind": "selector_present", "substring": "section.projects-grid"},
            ],
        }
        ei = {"scenario": "kmbl_static_frontend_pass_n_v1", "constraints": {"canonical_vertical": "static_frontend_file_v1"}}
        out, fixes = soften_portfolio_evaluation_targets(raw, ei)
        assert fixes == []
        assert out is raw

    def test_noop_when_interactive_vertical(self) -> None:
        raw = {
            "build_spec": {"type": "interactive_frontend_app_v1"},
            "evaluation_targets": [
                {"kind": "selector_present", "substring": "section.projects-grid"},
            ],
        }
        ei = {
            "scenario": "kmbl_identity_url_static_v1",
            "constraints": {"canonical_vertical": "interactive_frontend_app_v1"},
        }
        out, fixes = soften_portfolio_evaluation_targets(raw, ei)
        assert fixes == []

    def test_noop_when_empty_targets(self) -> None:
        raw = {
            "build_spec": self._build_spec_static(),
            "evaluation_targets": [],
        }
        ei = self._identity_url_event_input()
        out, fixes = soften_portfolio_evaluation_targets(raw, ei)
        assert fixes == []

    def test_preserves_string_targets(self) -> None:
        raw = {
            "build_spec": self._build_spec_static(),
            "evaluation_targets": [
                "text must appear",
                {"kind": "selector_present", "substring": "section.about-career"},
            ],
        }
        ei = self._identity_url_event_input()
        out, fixes = soften_portfolio_evaluation_targets(raw, ei)
        assert len(fixes) == 1
        assert len(out["evaluation_targets"]) == 1
        assert out["evaluation_targets"][0] == "text must appear"

    def test_handles_selector_key_variant(self) -> None:
        """Some targets use 'selector' key instead of 'substring'."""
        raw = {
            "build_spec": self._build_spec_static(),
            "evaluation_targets": [
                {"kind": "selector_present", "selector": "section.projects-grid"},
                {"kind": "text_present", "substring": "Hello"},
            ],
        }
        ei = self._identity_url_event_input()
        out, fixes = soften_portfolio_evaluation_targets(raw, ei)
        assert len(fixes) == 1
        assert len(out["evaluation_targets"]) == 1

    def test_does_not_mutate_input(self) -> None:
        targets = [
            {"kind": "text_present", "substring": "Harvey Lacsina"},
            {"kind": "selector_present", "substring": "section.projects-grid"},
        ]
        raw = {
            "build_spec": self._build_spec_static(),
            "evaluation_targets": list(targets),
        }
        ei = self._identity_url_event_input()
        out, fixes = soften_portfolio_evaluation_targets(raw, ei)
        # Original raw should be unchanged
        assert len(raw["evaluation_targets"]) == 2
        assert len(out["evaluation_targets"]) == 1
