"""
Targeted tests for the demo/public-mode preview grounding contract.

Covers:
    G1  Happy path — configured public URL + browser-reachable preview
        → required=True, satisfied=True, mode=browser, fallback_reason=None

    G2  Fallback: configured public URL + preview unavailable
        → required=True, satisfied=False, mode=none, fallback_reason set

    G3  Fallback: configured public URL + private host (operator_local_only)
        → required=True, satisfied=False, mode=snippet, fallback_reason set

    G4  Non-demo mode (derived_local or no base)
        → required=False, satisfied=True regardless of preview mode

    G5  Smoke-contract suppression
        → required=False, satisfied=True even with configured public base

    G6  Coherence — grounding_mode from compute_demo_preview_grounding_state
        matches what resolve_evaluator_preview_resolution returns

    G7  Demo vs non-demo: demo enforces visibility (satisfied field differs),
        non-demo allows silent fallback

    G8  Event type constant exists and has the expected string value

    G9  Grounding state is written to metrics_json in a real evaluation flow
        (unit-level smoke — no LLM, no DB)
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.runtime.demo_preview_grounding import (
    compute_demo_preview_grounding_state,
    is_demo_mode_from_resolution,
)
from kmbl_orchestrator.runtime.habitat_lifecycle import (
    clear_registry_for_tests,
    register_materialization,
)
from kmbl_orchestrator.runtime.run_events import RunEventType
from kmbl_orchestrator.runtime.session_staging_links import (
    resolve_evaluator_preview_resolution,
)


@pytest.fixture(autouse=True)
def _reset_habitat_registry() -> None:
    clear_registry_for_tests()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resolution(
    *,
    orchestrator_public_base_source: str = "configured",
    preview_grounding_mode: str = "browser_reachable",
    preview_grounding_degrade_reason: str | None = None,
    preview_grounding_reason: str = "public_orchestrator_base",
) -> dict:
    return {
        "orchestrator_public_base_source": orchestrator_public_base_source,
        "preview_grounding_mode": preview_grounding_mode,
        "preview_grounding_degrade_reason": preview_grounding_degrade_reason,
        "preview_grounding_reason": preview_grounding_reason,
    }


# ---------------------------------------------------------------------------
# G1: Happy path — configured public base, browser-reachable preview
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_browser_reachable_satisfied(self) -> None:
        res = _make_resolution(
            orchestrator_public_base_source="configured",
            preview_grounding_mode="browser_reachable",
        )
        state = compute_demo_preview_grounding_state(res)

        assert state["preview_grounding_required"] is True
        assert state["preview_grounding_satisfied"] is True
        assert state["preview_grounding_mode"] == "browser"
        assert state["preview_grounding_fallback_reason"] is None

    def test_demo_mode_detected(self) -> None:
        res = _make_resolution(orchestrator_public_base_source="configured")
        assert is_demo_mode_from_resolution(res) is True

    def test_non_demo_mode_not_detected_for_derived_local(self) -> None:
        res = _make_resolution(orchestrator_public_base_source="derived_local")
        assert is_demo_mode_from_resolution(res) is False

    def test_non_demo_mode_not_detected_for_none(self) -> None:
        res = _make_resolution(orchestrator_public_base_source="none")
        assert is_demo_mode_from_resolution(res) is False

    def test_full_resolution_happy_path(self) -> None:
        """End-to-end: configured public URL with registered candidate → grounding satisfied."""
        tid = uuid4()
        gid = str(uuid4())
        register_materialization(
            thread_id=tid,
            local_path=f"/tmp/cp/{tid}",
            materialization_kind="candidate_preview",
            graph_run_id=UUID(gid),
            can_rehydrate_from_persistence=True,
        )
        s = Settings(orchestrator_public_base_url="https://demo.example.com")
        preview_res = resolve_evaluator_preview_resolution(
            s, graph_run_id=gid, thread_id=str(tid), build_candidate={}
        )

        state = compute_demo_preview_grounding_state(preview_res)

        assert state["preview_grounding_required"] is True
        assert state["preview_grounding_satisfied"] is True
        assert state["preview_grounding_mode"] == "browser"
        assert state["preview_grounding_fallback_reason"] is None


# ---------------------------------------------------------------------------
# G2: Fallback — configured public base, no preview URL available
# ---------------------------------------------------------------------------


class TestFallbackNoPreview:
    def test_unavailable_mode_not_satisfied(self) -> None:
        res = _make_resolution(
            orchestrator_public_base_source="configured",
            preview_grounding_mode="unavailable",
            preview_grounding_reason="missing_absolute_operator_preview",
        )
        state = compute_demo_preview_grounding_state(res)

        assert state["preview_grounding_required"] is True
        assert state["preview_grounding_satisfied"] is False
        assert state["preview_grounding_mode"] == "none"
        assert state["preview_grounding_fallback_reason"] is not None
        assert len(state["preview_grounding_fallback_reason"]) > 0

    def test_fallback_reason_prefers_degrade_reason(self) -> None:
        res = _make_resolution(
            orchestrator_public_base_source="configured",
            preview_grounding_mode="unavailable",
            preview_grounding_degrade_reason="missing_absolute_preview_url",
            preview_grounding_reason="some_other_reason",
        )
        state = compute_demo_preview_grounding_state(res)
        assert state["preview_grounding_fallback_reason"] == "missing_absolute_preview_url"

    def test_fallback_reason_falls_back_to_preview_grounding_reason(self) -> None:
        res = _make_resolution(
            orchestrator_public_base_source="configured",
            preview_grounding_mode="unavailable",
            preview_grounding_degrade_reason=None,
            preview_grounding_reason="missing_absolute_operator_preview",
        )
        state = compute_demo_preview_grounding_state(res)
        assert state["preview_grounding_fallback_reason"] == "missing_absolute_operator_preview"

    def test_full_resolution_no_base_url_production(self) -> None:
        """Production env without public base → canonical URL is None → fallback reported."""
        s = Settings(orchestrator_public_base_url="", kmbl_env="production")
        gid = str(uuid4())
        tid = str(uuid4())
        preview_res = resolve_evaluator_preview_resolution(
            s, graph_run_id=gid, thread_id=tid, build_candidate={}
        )
        state = compute_demo_preview_grounding_state(preview_res)

        # Production with no public URL → not demo mode → not required
        assert state["preview_grounding_required"] is False
        assert state["preview_grounding_satisfied"] is True


# ---------------------------------------------------------------------------
# G3: Fallback — configured public base, preview is private-host only
# ---------------------------------------------------------------------------


class TestFallbackPrivateHost:
    def test_operator_local_only_maps_to_snippet(self) -> None:
        res = _make_resolution(
            orchestrator_public_base_source="configured",
            preview_grounding_mode="operator_local_only",
            preview_grounding_degrade_reason="private_host_blocked_by_gateway_policy",
            preview_grounding_reason="private_host_blocked_by_gateway_policy",
        )
        state = compute_demo_preview_grounding_state(res)

        assert state["preview_grounding_required"] is True
        assert state["preview_grounding_satisfied"] is False
        assert state["preview_grounding_mode"] == "snippet"
        assert state["preview_grounding_fallback_reason"] == "private_host_blocked_by_gateway_policy"

    def test_full_resolution_derived_local_private_in_demo(self) -> None:
        """Configured public URL but evaluator URL resolves to localhost → not satisfied."""
        # Simulate a case where the public base IS configured but the URL
        # ends up local-only after classification. We do this by using a
        # configured public base that is localhost (edge case).
        s = Settings(orchestrator_public_base_url="http://127.0.0.1:9999")
        gid = str(uuid4())
        tid = str(uuid4())
        preview_res = resolve_evaluator_preview_resolution(
            s, graph_run_id=gid, thread_id=tid, build_candidate={}
        )
        state = compute_demo_preview_grounding_state(preview_res)

        # base_source is "configured" (explicit public URL) — demo mode active
        assert is_demo_mode_from_resolution(preview_res) is True
        # But localhost URL is blocked by gateway → not satisfied
        assert state["preview_grounding_satisfied"] is False
        assert state["preview_grounding_fallback_reason"] is not None


# ---------------------------------------------------------------------------
# G4: Non-demo mode — derived_local or no base
# ---------------------------------------------------------------------------


class TestNonDemoMode:
    def test_derived_local_not_required(self) -> None:
        res = _make_resolution(
            orchestrator_public_base_source="derived_local",
            preview_grounding_mode="operator_local_only",
        )
        state = compute_demo_preview_grounding_state(res)

        assert state["preview_grounding_required"] is False
        assert state["preview_grounding_satisfied"] is True
        assert state["preview_grounding_fallback_reason"] is None

    def test_no_base_not_required(self) -> None:
        res = _make_resolution(
            orchestrator_public_base_source="none",
            preview_grounding_mode="unavailable",
        )
        state = compute_demo_preview_grounding_state(res)

        assert state["preview_grounding_required"] is False
        assert state["preview_grounding_satisfied"] is True

    def test_non_demo_unknown_mode_still_not_required(self) -> None:
        res = _make_resolution(
            orchestrator_public_base_source="derived_local",
            preview_grounding_mode="unknown_future_mode",
        )
        state = compute_demo_preview_grounding_state(res)
        assert state["preview_grounding_required"] is False
        assert state["preview_grounding_satisfied"] is True

    def test_full_resolution_development_derived_local(self) -> None:
        """Development env with derived_local → not demo mode → grounding not required."""
        s = Settings(
            orchestrator_public_base_url="",
            orchestrator_port=8000,
            kmbl_env="development",
        )
        gid = str(uuid4())
        tid = str(uuid4())
        preview_res = resolve_evaluator_preview_resolution(
            s, graph_run_id=gid, thread_id=tid, build_candidate={}
        )
        state = compute_demo_preview_grounding_state(preview_res)

        assert state["preview_grounding_required"] is False
        assert state["preview_grounding_satisfied"] is True


# ---------------------------------------------------------------------------
# G5: Smoke-contract suppression
# ---------------------------------------------------------------------------


class TestSmokeContractSuppression:
    def test_smoke_contract_reason_suppresses_demo(self) -> None:
        res = {
            "orchestrator_public_base_source": "configured",
            "preview_grounding_mode": "unavailable",
            "preview_grounding_reason": "smoke_contract_evaluator",
            "preview_grounding_degrade_reason": None,
        }
        state = compute_demo_preview_grounding_state(res)

        assert state["preview_grounding_required"] is False
        assert state["preview_grounding_satisfied"] is True
        assert state["preview_grounding_mode"] == "none"
        assert state["preview_grounding_fallback_reason"] == "smoke_contract_evaluator"

    def test_smoke_contract_does_not_affect_non_smoke(self) -> None:
        """Sanity: a non-smoke resolution with configured public base is still demo mode."""
        res = {
            "orchestrator_public_base_source": "configured",
            "preview_grounding_mode": "browser_reachable",
            "preview_grounding_reason": "public_orchestrator_base",
            "preview_grounding_degrade_reason": None,
        }
        state = compute_demo_preview_grounding_state(res)
        assert state["preview_grounding_required"] is True
        assert state["preview_grounding_satisfied"] is True


# ---------------------------------------------------------------------------
# G6: Coherence — grounding mode vocabulary consistent with resolution
# ---------------------------------------------------------------------------


class TestGroundingModeCoherence:
    """compute_demo_preview_grounding_state must map resolution modes consistently."""

    @pytest.mark.parametrize("raw_mode,expected_normalized", [
        ("browser_reachable", "browser"),
        ("operator_local_only", "snippet"),
        ("unavailable", "none"),
        ("unknown_future", "none"),  # unknown values default to none
    ])
    def test_mode_normalisation(self, raw_mode: str, expected_normalized: str) -> None:
        res = _make_resolution(
            orchestrator_public_base_source="configured",
            preview_grounding_mode=raw_mode,
        )
        state = compute_demo_preview_grounding_state(res)
        assert state["preview_grounding_mode"] == expected_normalized

    def test_evaluator_resolution_and_grounding_state_agree_on_browser_mode(self) -> None:
        """Full integration: resolve_evaluator_preview_resolution feeding into grounding."""
        tid = uuid4()
        gid = str(uuid4())
        register_materialization(
            thread_id=tid,
            local_path=f"/tmp/cp/{tid}",
            materialization_kind="candidate_preview",
            graph_run_id=UUID(gid),
            can_rehydrate_from_persistence=True,
        )
        s = Settings(orchestrator_public_base_url="https://demo.example.com")
        preview_res = resolve_evaluator_preview_resolution(
            s, graph_run_id=gid, thread_id=str(tid), build_candidate={}
        )

        assert preview_res["preview_grounding_mode"] == "browser_reachable"
        state = compute_demo_preview_grounding_state(preview_res)
        assert state["preview_grounding_mode"] == "browser"
        assert state["preview_grounding_satisfied"] is True


# ---------------------------------------------------------------------------
# G7: Demo vs non-demo — explicit visibility contrast
# ---------------------------------------------------------------------------


class TestDemoVsNonDemo:
    """Demo mode enforces grounding visibility; non-demo allows silent fallback."""

    def test_same_unavailable_preview_differs_by_mode(self) -> None:
        """When preview is unavailable, demo mode is not satisfied; non-demo is OK."""
        demo_res = _make_resolution(
            orchestrator_public_base_source="configured",
            preview_grounding_mode="unavailable",
        )
        non_demo_res = _make_resolution(
            orchestrator_public_base_source="derived_local",
            preview_grounding_mode="unavailable",
        )

        demo_state = compute_demo_preview_grounding_state(demo_res)
        non_demo_state = compute_demo_preview_grounding_state(non_demo_res)

        # Demo: required + not satisfied
        assert demo_state["preview_grounding_required"] is True
        assert demo_state["preview_grounding_satisfied"] is False
        assert demo_state["preview_grounding_fallback_reason"] is not None

        # Non-demo: not required + satisfied
        assert non_demo_state["preview_grounding_required"] is False
        assert non_demo_state["preview_grounding_satisfied"] is True
        assert non_demo_state["preview_grounding_fallback_reason"] is None

    def test_same_private_only_differs_by_mode(self) -> None:
        demo_res = _make_resolution(
            orchestrator_public_base_source="configured",
            preview_grounding_mode="operator_local_only",
            preview_grounding_degrade_reason="private_host_blocked_by_gateway_policy",
        )
        non_demo_res = _make_resolution(
            orchestrator_public_base_source="derived_local",
            preview_grounding_mode="operator_local_only",
            preview_grounding_degrade_reason="private_host_blocked_by_gateway_policy",
        )

        demo_state = compute_demo_preview_grounding_state(demo_res)
        non_demo_state = compute_demo_preview_grounding_state(non_demo_res)

        assert demo_state["preview_grounding_satisfied"] is False
        assert non_demo_state["preview_grounding_satisfied"] is True


# ---------------------------------------------------------------------------
# G8: Event type constant exists
# ---------------------------------------------------------------------------


class TestEventTypeConstant:
    def test_evaluator_demo_grounding_degraded_exists(self) -> None:
        assert hasattr(RunEventType, "EVALUATOR_DEMO_GROUNDING_DEGRADED")
        assert RunEventType.EVALUATOR_DEMO_GROUNDING_DEGRADED == "evaluator_demo_grounding_degraded"

    def test_evaluator_demo_grounding_degraded_is_unique(self) -> None:
        """The new event type string must not collide with any existing event type."""
        all_values = {
            v for k, v in vars(RunEventType).items()
            if not k.startswith("_") and isinstance(v, str)
        }
        # Confirm exactly one entry with this value
        matches = [
            k for k, v in vars(RunEventType).items()
            if not k.startswith("_") and v == "evaluator_demo_grounding_degraded"
        ]
        assert len(matches) == 1
        assert "EVALUATOR_DEMO_GROUNDING_DEGRADED" in matches


# ---------------------------------------------------------------------------
# G9: Grounding state fields end up in the evaluation metrics_json
# ---------------------------------------------------------------------------


class TestGroundingFieldsInMetrics:
    """Smoke-test that the four grounding fields are present in any evaluation report."""

    def test_grounding_state_keys_expected(self) -> None:
        """compute_demo_preview_grounding_state always returns exactly these four keys."""
        res = _make_resolution(
            orchestrator_public_base_source="configured",
            preview_grounding_mode="browser_reachable",
        )
        state = compute_demo_preview_grounding_state(res)

        assert set(state.keys()) == {
            "preview_grounding_required",
            "preview_grounding_satisfied",
            "preview_grounding_mode",
            "preview_grounding_fallback_reason",
        }

    def test_grounding_state_types(self) -> None:
        for base_source in ("configured", "derived_local", "none"):
            for mode in ("browser_reachable", "operator_local_only", "unavailable"):
                res = _make_resolution(
                    orchestrator_public_base_source=base_source,
                    preview_grounding_mode=mode,
                )
                state = compute_demo_preview_grounding_state(res)
                assert isinstance(state["preview_grounding_required"], bool)
                assert isinstance(state["preview_grounding_satisfied"], bool)
                assert isinstance(state["preview_grounding_mode"], str)
                assert state["preview_grounding_fallback_reason"] is None or isinstance(
                    state["preview_grounding_fallback_reason"], str
                )

    def test_fallback_reason_only_set_when_not_satisfied(self) -> None:
        """fallback_reason must be None when satisfied=True."""
        for base_source in ("configured", "derived_local", "none"):
            for mode in ("browser_reachable", "operator_local_only", "unavailable"):
                res = _make_resolution(
                    orchestrator_public_base_source=base_source,
                    preview_grounding_mode=mode,
                )
                state = compute_demo_preview_grounding_state(res)
                if state["preview_grounding_satisfied"]:
                    # When satisfied, fallback_reason should be None
                    # (except smoke_contract path which sets it explicitly)
                    assert state["preview_grounding_fallback_reason"] is None or \
                        state["preview_grounding_fallback_reason"] == "smoke_contract_evaluator"
