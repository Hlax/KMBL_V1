"""
KMBL-side OpenClaw **provider_config_key** selection for generator invocations.

Only **generator** may be routed to the image OpenClaw agent (``kmbl-image-gen``) for explicit
image-generation work. Planner and evaluator always use their default ``openclaw_*_config_key``.

When image intent is present, routing **requires** ``OPENCLAW_GENERATOR_OPENAI_IMAGE_CONFIG_KEY``
(typically ``kmbl-image-gen``). There is **no** silent fallback to ``kmbl-generator``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from kmbl_orchestrator.config import Settings
import kmbl_orchestrator.runtime.image_generation_intent as _image_intent
from kmbl_orchestrator.runtime.openai_hourly_budget import (
    OpenAIImageBudgetStore,
    check_or_consume_openai_image_budget,
    get_openai_hourly_budget_guard,
)

extract_image_generation_intent = _image_intent.extract_image_generation_intent
should_use_openai_for_image_generation = _image_intent.should_use_openai_for_image_generation

_LOG = logging.getLogger(__name__)


class ImageRouteConfigurationError(ValueError):
    """Image generation intent is present but ``OPENCLAW_GENERATOR_OPENAI_IMAGE_CONFIG_KEY`` is unset."""


class ImageRouteBudgetExceededError(ValueError):
    """Hourly estimated-token budget for the image OpenClaw route is exhausted."""


def estimate_openai_image_route_tokens(settings: Settings, payload: dict[str, Any]) -> int:
    """Conservative token estimate for one generator invocation (marked estimated in metadata)."""
    base = max(1, int(settings.kmb_openai_image_route_estimated_tokens_per_invocation))
    try:
        raw = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        raw = ""
    bump = min(len(raw) // 2, 32_000)
    return min(base + bump, 256_000)


def _base_routing_metadata(
    *,
    cap: int,
    intent_kind: str,
    image_requested: bool,
    openai_requested: bool,
    route_reason: str,
    budget_used: int,
    budget_remaining: int,
) -> dict[str, Any]:
    return {
        "kmb_routing_version": 3,
        "generator_route_kind": "default",
        "image_generation_requested": image_requested,
        "image_requested": image_requested,
        "image_generation_intent_kind": intent_kind,
        "openai_image_route_requested": openai_requested,
        "openai_image_route_applied": False,
        "provider_config_key": None,
        "budget_denial_reason": None,
        "estimated_tokens_reserved": None,
        "budget_cap_tokens": cap,
        "budget_used_tokens_after_decision": budget_used,
        "budget_remaining_tokens": budget_remaining,
        "route_reason": route_reason,
        "budget_policy": "rolling_hourly_estimated_tokens",
    }


def select_generator_provider_config(
    settings: Settings,
    *,
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
    generator_payload: dict[str, Any],
    budget_store: OpenAIImageBudgetStore | None = None,
    now: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Return ``(openclaw provider_config_key, routing_metadata_json)`` for persistence and logs.

    Default path: ``settings.openclaw_generator_config_key``.

    Image path: ``settings.openclaw_generator_openai_image_config_key`` (default ``kmbl-image-gen``)
    when explicit image intent matches **and** hourly budget allows. If intent is present but the
    key is empty, raises :class:`ImageRouteConfigurationError`. If budget blocks, raises
    :class:`ImageRouteBudgetExceededError`.
    """
    cap = int(settings.kmb_openai_image_hourly_token_cap)
    store = budget_store or get_openai_hourly_budget_guard(cap)

    intent = extract_image_generation_intent(
        event_input=event_input,
        build_spec=build_spec,
        generator_payload=generator_payload,
    )
    image_requested = intent.kind != "none"

    intent_kind = intent.kind if image_requested else "none"
    default_key = (settings.openclaw_generator_config_key or "kmbl-generator").strip()
    alt_key = (settings.openclaw_generator_openai_image_config_key or "").strip()

    used0 = store.usage_in_window(now=now)
    rem0 = max(0, store.cap_tokens - used0)

    if not image_requested:
        meta = _base_routing_metadata(
            cap=store.cap_tokens,
            intent_kind="none",
            image_requested=False,
            openai_requested=False,
            route_reason=intent.route_reason,
            budget_used=used0,
            budget_remaining=rem0,
        )
        return default_key, meta

    if not alt_key:
        _LOG.error(
            "generator routing: image intent but OPENCLAW_GENERATOR_OPENAI_IMAGE_CONFIG_KEY is unset"
        )
        raise ImageRouteConfigurationError(
            "Image generation intent requires OPENCLAW_GENERATOR_OPENAI_IMAGE_CONFIG_KEY "
            "(e.g. kmbl-image-gen). Orchestrator does not call OpenAI Images directly."
        )

    est = estimate_openai_image_route_tokens(settings, generator_payload)
    decision = check_or_consume_openai_image_budget(store, est, now=now)

    meta = _base_routing_metadata(
        cap=decision.cap_tokens,
        intent_kind=intent_kind,
        image_requested=True,
        openai_requested=True,
        route_reason=intent.route_reason,
        budget_used=decision.used_tokens_after,
        budget_remaining=decision.remaining_tokens_after,
    )
    meta["estimated_tokens_reserved"] = est
    meta["budget_estimate_note"] = "conservative_estimate_pre_invoke"

    if not decision.allowed:
        _LOG.warning(
            "generator routing: OpenAI image route blocked by budget reason=%s",
            decision.denial_reason,
        )
        raise ImageRouteBudgetExceededError(
            f"OpenAI image route hourly budget exhausted: {decision.denial_reason or 'denied'}"
        )

    meta["openai_image_route_applied"] = True
    meta["generator_route_kind"] = "openclaw_image_agent"
    meta["route_reason"] = "openclaw_image_agent_route_applied"
    meta["provider_config_key"] = alt_key
    meta["provider_config_key_resolved"] = alt_key
    meta["budget_used_tokens_after_decision"] = decision.used_tokens_after
    _LOG.info("generator routing: using OpenClaw image agent config key=%s", alt_key)
    return alt_key, meta


__all__ = [
    "ImageRouteBudgetExceededError",
    "ImageRouteConfigurationError",
    "estimate_openai_image_route_tokens",
    "extract_image_generation_intent",
    "select_generator_provider_config",
    "should_use_openai_for_image_generation",
]
