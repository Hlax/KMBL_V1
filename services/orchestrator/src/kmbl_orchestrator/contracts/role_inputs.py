"""Validated outbound payloads to KiloClaw (orchestrator → provider boundary)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

RoleType = Literal["planner", "generator", "evaluator"]


class PlannerRoleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    graph_run_id: str | None = Field(
        default=None,
        description=(
            "Orchestrator graph run id — echoed for OpenClaw chat-completions `user` isolation; "
            "not part of planner agent semantics."
        ),
    )
    identity_context: dict[str, Any] = Field(default_factory=dict)
    memory_context: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "May include cross_run: { taste_summary, prompt_hints, items, read_trace } from "
            "identity_cross_run_memory; API may inject other keys — bias only, not identity override."
        ),
    )
    event_input: dict[str, Any] = Field(default_factory=dict)
    current_state_summary: dict[str, Any] = Field(default_factory=dict)
    working_staging_facts: dict[str, Any] | None = Field(
        default=None,
        description="Structured summary of current working staging surface for continuation context.",
    )
    user_rating_context: dict[str, Any] | None = Field(
        default=None,
        description="User's rating and feedback from the most recent staging snapshot.",
    )
    user_interrupts: list[dict[str, Any]] | None = Field(
        default=None,
        description="User interrupt messages from the autonomous loop.",
    )
    identity_url: str | None = Field(
        default=None,
        description=(
            "Echo of event_input.identity_url when present — source URL for identity extraction "
            "and optional Playwright/mcporter grounding (kmbl-planner)."
        ),
    )
    structured_identity: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Structured identity profile: themes, tone, visual_tendencies, content_types, "
            "complexity, notable_entities. Derived deterministically from identity signals. "
            "Use for experience_mode selection and identity-driven planning decisions."
        ),
    )
    replan_context: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Mid-run replan when orchestrator routes iterate → planner (iteration_index > 0): "
            "prior evaluation summary, prior build_spec, retry_context, prior_build_spec_id."
        ),
    )
    crawl_context: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Durable crawl state for cross-session resumption. Includes: crawl_status, "
            "root_url, total_pages_crawled, visited_count, unvisited_count, "
            "next_urls_to_crawl, recent_page_summaries, is_exhausted. "
            "Use to decide what pages to inspect next via Playwright MCP."
        ),
    )


class GeneratorRoleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    graph_run_id: str | None = Field(
        default=None,
        description=(
            "Orchestrator graph run id — echoed for OpenClaw chat-completions `user` isolation; "
            "not part of generator agent semantics."
        ),
    )
    build_spec: dict[str, Any] = Field(default_factory=dict)
    current_working_state: dict[str, Any] = Field(default_factory=dict)
    iteration_feedback: Any | None = None
    iteration_plan: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Orchestrator hint when iteration_feedback is set: treat evaluator output as the "
            "binding amendment plan; pivot_layout_strategy / iteration_strategy pivot vs refine "
            "(duplicate, fail, stagnation, rebuild pressure, or very low design_rubric on partial → pivot); "
            "stagnation_count and pressure_recommendation echo working staging."
        ),
    )
    event_input: dict[str, Any] = Field(default_factory=dict)
    working_staging_facts: dict[str, Any] | None = Field(
        default=None,
        description="Structured summary of current working staging surface for amendment context.",
    )
    # Identity brief: orchestrator-built constraints that survive past the planner boundary.
    # Contains: display_name, role_or_title, short_bio, palette_hex, tone_keywords,
    # aesthetic_keywords, layout_hints, headings_sample, must_mention, image_refs.
    # When present: must_mention items MUST appear in output. palette_hex MUST influence styling.
    identity_brief: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Orchestrator-built identity constraints injected directly (not via planner). "
            "Fields: identity_id, source_url, display_name, role_or_title, short_bio, "
            "palette_hex (use at least one), primary_palette, tone_keywords, aesthetic_keywords, "
            "layout_hints, headings_sample, must_mention (strings that MUST appear in output), "
            "image_refs, confidence, is_fallback."
        ),
    )
    structured_identity: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Structured identity profile: themes, tone, visual_tendencies, content_types, "
            "complexity, notable_entities. Use to shape generation decisions: "
            "map identity themes into spatial design, use 3D composition intentionally."
        ),
    )
    spatial_translation_hints: list[str] | None = Field(
        default=None,
        description=(
            "Deterministic mapping from visual tendencies to spatial design hints. "
            "E.g. 'map projects to 3D planes', 'use animated transitions and camera movement'."
        ),
    )
    cool_generation_lane_active: bool = Field(
        default=False,
        description=(
            "True when cool_generation_v1 lane is active (event_input.cool_generation_lane or "
            "build_spec.execution_contract.lane). Prefer kmbl_execution_contract + pattern_rules."
        ),
    )
    kmbl_execution_contract: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Compact obligations: lane, surface_type, layout_mode, pattern_rules, "
            "selected_reference_patterns, literal_success_checks_count, "
            "literal_success_checks_preview (first needles, truncated), creative_brief_mood."
        ),
    )
    surface_type: str = Field(
        default="static_html",
        description=(
            "Output surface shape for the generator: 'static_html' (standard HTML/CSS/JS) "
            "or 'webgl_experience' (canvas-based rendering with shader/config files). "
            "Derived from build_spec.experience_mode by the orchestrator."
        ),
    )


class EvaluatorRoleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    graph_run_id: str | None = Field(
        default=None,
        description=(
            "Orchestrator graph run id — echoed for OpenClaw chat-completions `user` isolation; "
            "not part of evaluator agent semantics."
        ),
    )
    build_candidate: dict[str, Any] = Field(default_factory=dict)
    success_criteria: list[Any] = Field(default_factory=list)
    evaluation_targets: list[Any] = Field(default_factory=list)
    iteration_hint: int = 0
    working_staging_facts: dict[str, Any] | None = Field(
        default=None,
        description="Structured summary of current working staging surface for evaluation context.",
    )
    user_rating_context: dict[str, Any] | None = Field(
        default=None,
        description="User's rating and feedback from prior staging snapshots for calibration.",
    )
    # Identity brief: same object passed to generator. Evaluator uses must_mention,
    # palette_hex, tone_keywords to produce alignment_report in output.
    identity_brief: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Same identity brief passed to generator. Use to produce alignment_report: "
            "check must_mention items present, palette colors used, tone reflected. "
            "Report as alignment_report block in output metrics."
        ),
    )
    structured_identity: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Structured identity profile: themes, tone, visual_tendencies, content_types, "
            "complexity. Use for intent-aware evaluation: check alignment with identity themes, "
            "whether spatial/3D decisions reflect intent, whether flat fallback is justified."
        ),
    )
    preview_url: str | None = Field(
        default=None,
        description=(
            "Resolved preview URL for visual evaluation — prefers orchestrator staging-preview "
            "when orchestrator_public_base_url is set, else build_candidate.preview_url."
        ),
    )
    iteration_context: dict[str, Any] | None = Field(
        default=None,
        description="Iteration index and flags for bounded visual-delta evaluation.",
    )
    previous_evaluation_report: dict[str, Any] | None = Field(
        default=None,
        description="Prior evaluator JSON on this run when iteration_hint > 0 (sameness / delta).",
    )


def validate_role_input(role_type: RoleType, payload: dict[str, Any]) -> dict[str, Any]:
    """Returns a JSON-safe dict for the provider. Raises ValidationError on bad input."""
    if role_type == "planner":
        return PlannerRoleInput.model_validate(payload).model_dump(mode="json")
    if role_type == "generator":
        return GeneratorRoleInput.model_validate(payload).model_dump(mode="json")
    if role_type == "evaluator":
        return EvaluatorRoleInput.model_validate(payload).model_dump(mode="json")
    raise ValueError(f"unknown role_type: {role_type}")


__all__ = [
    "EvaluatorRoleInput",
    "GeneratorRoleInput",
    "PlannerRoleInput",
    "RoleType",
    "validate_role_input",
    "ValidationError",
]
