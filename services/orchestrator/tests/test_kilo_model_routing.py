"""KMBL generator OpenClaw routing, image intent extraction, and hourly token budget."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.runtime.image_generation_intent import (
    extract_image_generation_intent,
    should_use_openai_for_image_generation,
)
from kmbl_orchestrator.runtime.kilo_model_routing import (
    ImageRouteBudgetExceededError,
    ImageRouteConfigurationError,
    select_generator_provider_config,
)
from kmbl_orchestrator.runtime.openai_hourly_budget import (
    OpenAIHourlyBudgetGuard,
    check_or_consume_openai_image_budget,
    reset_openai_hourly_budget_guard_for_tests,
)
from kmbl_orchestrator.seeds import (
    KILOCLAW_IMAGE_ONLY_TEST_SCENARIO_TAG,
    SEEDED_GALLERY_STRIP_SCENARIO_TAG,
)

T0 = datetime(2020, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _meta_keys() -> set[str]:
    return {
        "kmb_routing_version",
        "generator_route_kind",
        "image_generation_requested",
        "image_requested",
        "image_generation_intent_kind",
        "openai_image_route_requested",
        "openai_image_route_applied",
        "provider_config_key",
        "budget_denial_reason",
        "estimated_tokens_reserved",
        "budget_cap_tokens",
        "budget_used_tokens_after_decision",
        "budget_remaining_tokens",
        "route_reason",
        "budget_policy",
    }


def test_routing_metadata_stable_shape() -> None:
    reset_openai_hourly_budget_guard_for_tests()
    s = Settings.model_construct(
        kiloclaw_generator_config_key="kmbl-generator",
        kiloclaw_generator_openai_image_config_key="kmbl-gen-openai",
        kmb_openai_image_hourly_token_cap=1_500_000,
        kmb_openai_image_route_estimated_tokens_per_invocation=10_000,
    )
    _, meta = select_generator_provider_config(
        s,
        build_spec={"type": "generic"},
        event_input={"scenario": SEEDED_GALLERY_STRIP_SCENARIO_TAG},
        generator_payload={"thread_id": "x"},
        budget_store=OpenAIHourlyBudgetGuard(1_500_000, now_fn=lambda: T0),
        now=T0,
    )
    assert _meta_keys().issubset(meta.keys())


def test_should_use_openai_gallery_scenario() -> None:
    assert should_use_openai_for_image_generation(
        event_input={"scenario": SEEDED_GALLERY_STRIP_SCENARIO_TAG},
        build_spec={},
    )


def test_kiloclaw_image_only_test_scenario_has_intent() -> None:
    intent = extract_image_generation_intent(
        event_input={"scenario": KILOCLAW_IMAGE_ONLY_TEST_SCENARIO_TAG},
        build_spec={},
        generator_payload={},
    )
    assert intent.kind == "gallery_strip_image_v1"
    assert intent.route_reason == "kiloclaw_image_only_test_v1"


def test_should_not_use_openai_generic_build() -> None:
    assert not should_use_openai_for_image_generation(
        event_input={"scenario": "other"},
        build_spec={"type": "app", "title": "x"},
    )


def test_vague_aesthetic_not_image_intent() -> None:
    assert should_use_openai_for_image_generation(
        event_input={},
        build_spec={"title": "Landing", "notes": "make it beautiful and polished"},
    ) is False


def test_hero_banner_artifact_explicit() -> None:
    intent = extract_image_generation_intent(
        event_input={},
        build_spec={"artifact_outputs": [{"role": "hero_banner_image_v1", "key": "x"}]},
        generator_payload={},
    )
    assert intent.kind == "hero_banner_image_v1"


def test_non_image_generator_payload_default_route() -> None:
    reset_openai_hourly_budget_guard_for_tests()
    s = Settings.model_construct(
        kiloclaw_generator_config_key="kmbl-generator",
        kiloclaw_generator_openai_image_config_key="kmbl-gen-openai",
        kmb_openai_image_hourly_token_cap=1_500_000,
        kmb_openai_image_route_estimated_tokens_per_invocation=10_000,
    )
    key, meta = select_generator_provider_config(
        s,
        build_spec={"type": "generic"},
        event_input={},
        generator_payload={"thread_id": "x"},
        budget_store=OpenAIHourlyBudgetGuard(1_500_000, now_fn=lambda: T0),
        now=T0,
    )
    assert key == "kmbl-generator"
    assert meta["openai_image_route_requested"] is False
    assert meta["openai_image_route_applied"] is False
    assert meta["image_generation_intent_kind"] == "none"


def test_gallery_under_budget_routes_to_kiloclaw_image_agent() -> None:
    reset_openai_hourly_budget_guard_for_tests()
    s = Settings.model_construct(
        kiloclaw_generator_config_key="kmbl-generator",
        kiloclaw_generator_openai_image_config_key="kmbl-gen-openai",
        kmb_openai_image_hourly_token_cap=1_500_000,
        kmb_openai_image_route_estimated_tokens_per_invocation=10_000,
    )
    guard = OpenAIHourlyBudgetGuard(1_500_000, now_fn=lambda: T0)
    key, meta = select_generator_provider_config(
        s,
        build_spec={},
        event_input={"scenario": SEEDED_GALLERY_STRIP_SCENARIO_TAG},
        generator_payload={"thread_id": "x"},
        budget_store=guard,
        now=T0,
    )
    assert key == "kmbl-gen-openai"
    assert meta["openai_image_route_applied"] is True
    assert meta["generator_route_kind"] == "kiloclaw_image_agent"
    assert meta["route_reason"] == "kiloclaw_image_agent_route_applied"
    assert meta["provider_config_key"] == "kmbl-gen-openai"
    assert meta["image_generation_intent_kind"] == "gallery_strip_image_v1"


def test_non_gallery_future_artifact_under_budget() -> None:
    reset_openai_hourly_budget_guard_for_tests()
    s = Settings.model_construct(
        kiloclaw_generator_config_key="kmbl-generator",
        kiloclaw_generator_openai_image_config_key="kmbl-gen-openai",
        kmb_openai_image_hourly_token_cap=1_500_000,
        kmb_openai_image_route_estimated_tokens_per_invocation=10_000,
    )
    key, meta = select_generator_provider_config(
        s,
        build_spec={"artifact_outputs": [{"role": "hero_banner_image_v1"}]},
        event_input={},
        generator_payload={"thread_id": "x"},
        budget_store=OpenAIHourlyBudgetGuard(1_500_000, now_fn=lambda: T0),
        now=T0,
    )
    assert key == "kmbl-gen-openai"
    assert meta["image_generation_intent_kind"] == "hero_banner_image_v1"
    assert meta["generator_route_kind"] == "kiloclaw_image_agent"


def test_image_intent_raises_when_alt_key_empty() -> None:
    reset_openai_hourly_budget_guard_for_tests()
    s = Settings.model_construct(
        kiloclaw_generator_config_key="kmbl-generator",
        kiloclaw_generator_openai_image_config_key="",
        kmb_openai_image_hourly_token_cap=1_500_000,
        kmb_openai_image_route_estimated_tokens_per_invocation=10_000,
    )
    with pytest.raises(ImageRouteConfigurationError):
        select_generator_provider_config(
            s,
            build_spec={},
            event_input={"scenario": SEEDED_GALLERY_STRIP_SCENARIO_TAG},
            generator_payload={"thread_id": "x"},
            budget_store=OpenAIHourlyBudgetGuard(1_500_000, now_fn=lambda: T0),
            now=T0,
        )


def test_budget_blocks_raises() -> None:
    reset_openai_hourly_budget_guard_for_tests()
    s = Settings.model_construct(
        kiloclaw_generator_config_key="kmbl-generator",
        kiloclaw_generator_openai_image_config_key="kmbl-gen-openai",
        kmb_openai_image_hourly_token_cap=1_500_000,
        kmb_openai_image_route_estimated_tokens_per_invocation=12_000,
    )
    guard = OpenAIHourlyBudgetGuard(100_000, now_fn=lambda: T0)
    assert guard.try_consume(95_000, now=T0).allowed is True
    with pytest.raises(ImageRouteBudgetExceededError):
        select_generator_provider_config(
            s,
            build_spec={},
            event_input={"scenario": SEEDED_GALLERY_STRIP_SCENARIO_TAG},
            generator_payload={"thread_id": "x"},
            budget_store=guard,
            now=T0,
        )


def test_budget_exact_fit_allowed() -> None:
    guard = OpenAIHourlyBudgetGuard(1_000, now_fn=lambda: T0)
    d = check_or_consume_openai_image_budget(guard, 1_000, now=T0)
    assert d.allowed is True
    assert d.used_tokens_after == 1_000
    assert d.remaining_tokens_after == 0


def test_budget_one_token_over_denied() -> None:
    guard = OpenAIHourlyBudgetGuard(1_000, now_fn=lambda: T0)
    d = check_or_consume_openai_image_budget(guard, 1_001, now=T0)
    assert d.allowed is False
    assert d.denial_reason == "hourly_token_budget_exhausted"


def test_budget_window_expires_entries() -> None:
    guard = OpenAIHourlyBudgetGuard(1_000, now_fn=lambda: T0)
    assert guard.try_consume(500, now=T0).allowed is True
    t1 = T0 + timedelta(hours=1, minutes=1)
    assert guard.usage_in_window(now=t1) == 0
    assert guard.try_consume(500, now=t1).allowed is True
    assert guard.usage_in_window(now=t1) == 500


def test_invoke_role_dev_routes_generator_only() -> None:
    from pathlib import Path

    p = Path(__file__).resolve().parents[1] / "src/kmbl_orchestrator/api/main.py"
    text = p.read_text(encoding="utf-8")
    i = text.index("def invoke_role")
    chunk = text[i : i + 4500]
    assert "select_generator_provider_config" in chunk
    gen_idx = chunk.index("select_generator_provider_config")
    assert 'if body.role_type == "generator"' in chunk[:gen_idx]


def test_planner_evaluator_cannot_use_openai_route_helpers() -> None:
    """Routing helpers are only invoked by generator path; planner-like payloads never match intent."""
    assert not should_use_openai_for_image_generation(
        event_input={"task": "plan only"},
        build_spec={"constraints": {}, "success_criteria": []},
    )
