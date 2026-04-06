"""Validated outbound payloads to KiloClaw (orchestrator → provider boundary)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kmbl_orchestrator.runtime.habitat_strategy import HabitatStrategy

RoleType = Literal["planner", "generator", "evaluator"]


class KmblHabitatRuntimeInput(BaseModel):
    """Orchestrator-enforced habitat semantics (see ``habitat_strategy.py``)."""

    model_config = ConfigDict(extra="forbid")

    effective_strategy: HabitatStrategy
    suppress_prior_working_surface: bool = Field(
        description=(
            "True when iteration 0 uses fresh_start/rebuild_informed and prior working surface "
            "must not be trusted as continuation context."
        ),
    )


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
            "Working crawl memory for cross-session resumption (NOT raw visit logs). "
            "Includes: crawl_phase (identity_grounding | inspiration_expansion), crawl_available, "
            "crawl_status, root_url, has_site_memory, has_reused_shared_site_crawl, counts, "
            "next_urls_to_crawl, top_identity_pages (ranked), top_inspiration_pages (ranked, only "
            "when phase is inspiration_expansion), recent_portfolio_summaries vs "
            "recent_inspiration_summaries (compact, origin-tagged), recent_page_summaries "
            "(short back-compat union), resume (has_prior_crawl_memory, frontier_internal_urls_remaining), "
            "freshness (site_memory_stale, days_since_site_memory_update, stale_after_days), "
            "memory_contract, evidence_contract (identity truth vs inspiration reference), "
            "grounding_available, is_exhausted, external_inspiration_available. "
            "Durable identity *seed* truth remains in identity_brief + structured_identity. "
            "\n\n"
            "When crawl_context is present and next_urls_to_crawl is non-empty, the planner "
            "MUST return `selected_urls` — the subset of next_urls_to_crawl URLs it actually "
            "consulted or used. Prefer exact absolute URLs from next_urls_to_crawl; relative "
            "paths (e.g. /about) are accepted and will be resolved against root_url. Do not "
            "invent URLs not in the offered set. Return [] if no frontier URLs were used. "
            "This enables tier-2 evidence (selected_by_planner) for auditable crawl progression."
        ),
    )
    kmbl_implementation_reference_cards: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Curated compact reference cards (official docs/examples) for planning — capped slice; "
            "see kmbl_reference_selection_meta."
        ),
    )
    kmbl_inspiration_reference_cards: list[dict[str, Any]] | None = Field(
        default=None,
        description="Design/taste reference cards — capped; not raw site content.",
    )
    kmbl_planner_observed_reference_cards: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Distilled cards from crawl/Playwright summaries (URLs + short notes) — ephemeral per crawl state; "
            "inline for this invocation only."
        ),
    )
    kmbl_reference_selection_meta: dict[str, Any] | None = Field(
        default=None,
        description="Counts, lane hints, library version — machine-usable selection audit.",
    )
    kmbl_reference_library_version: int | None = Field(
        default=None,
        description="Bundled curated reference_library JSON version.",
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
    workspace_context: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Orchestrator-resolved paths for local filesystem builds: workspace_root_resolved, "
            "recommended_write_path (typically {root}/{thread_id}/{graph_run_id}), "
            "canonical_preview_entry_relative (stable component/preview/index.html hint for sandbox layout). "
            "Generator should write only under recommended_write_path when emitting workspace_manifest_v1."
        ),
    )
    kmbl_prior_build_candidate_summary_v1: dict[str, Any] | None = Field(
        default=None,
        description=(
            "When iteration_index > 0: orchestrator ``build_candidate_summary_v1`` from the prior "
            "generator step — compact file inventory and heuristics; not a substitute for build_spec."
        ),
    )
    kmbl_prior_build_candidate_summary_v2: dict[str, Any] | None = Field(
        default=None,
        description=(
            "When iteration_index > 0: orchestrator ``build_candidate_summary_v2`` (artifact inspection) "
            "from the prior step — preferred over v1 for artifact-first retry context."
        ),
    )
    kmbl_habitat_runtime: KmblHabitatRuntimeInput | None = Field(
        default=None,
        description=(
            "Effective habitat strategy for this step and whether to suppress a stale prior surface; "
            "built in ``generator_node`` — generator must not infer this from cached canvas alone."
        ),
    )
    kmbl_interactive_lane_context: dict[str, Any] | None = Field(
        default=None,
        description=(
            "When ``build_spec.type`` / constraints select ``interactive_frontend_app_v1``: orchestrator "
            "hints for preview-safe bundles (strengths, avoid patterns, fairness notes), plus "
            "``generator_library_policy`` (default Three.js+GSAP lane, escalation rules, shader extensions). "
            "Omitted for other verticals."
        ),
    )
    kmbl_reference_patterns: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Interactive lane only: 1–3 compact pattern entries (lane-specific); duplicate of "
            "``kmbl_interactive_lane_context.reference_patterns`` for top-level visibility."
        ),
    )
    kmbl_library_compliance_hints: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Interactive lane only: soft policy signals (e.g. splat library without escalation_lane); "
            "not hard failures."
        ),
    )
    kmbl_implementation_reference_cards: list[dict[str, Any]] | None = Field(
        default=None,
        description="Interactive lane: capped curated implementation URLs/notes (generator mirror).",
    )
    kmbl_inspiration_reference_cards: list[dict[str, Any]] | None = Field(
        default=None,
        description="Interactive lane: capped taste/design reference cards.",
    )
    kmbl_planner_observed_reference_cards: list[dict[str, Any]] | None = Field(
        default=None,
        description="Interactive lane: crawl-distilled observed cards (same as generator when aligned).",
    )
    kmbl_reference_selection_meta: dict[str, Any] | None = Field(
        default=None,
        description="Interactive lane: selection meta for reference slices.",
    )
    kmbl_reference_library_version: int | None = Field(
        default=None,
        description="Bundled curated reference_library JSON version.",
    )
    kmbl_locked_build_spec_digest: str | None = Field(
        default=None,
        description=(
            "On iteration >= 1: short digest of the locked build_spec JSON (orchestrator retry compaction)."
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
    kmbl_build_candidate_summary_v1: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Echo of ``build_candidate.kmbl_build_candidate_summary_v1`` for top-level visibility: "
            "deterministic orchestrator summary of the bundle (no full file bodies)."
        ),
    )
    kmbl_build_candidate_summary_v2: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Orchestrator artifact-inspection v2 summary (canonical). Prefer this over v1 for "
            "preview-first evaluation; full bodies remain in persistence and deterministic gates."
        ),
    )
    kmbl_evaluator_artifact_snippets_v1: dict[str, Any] | None = Field(
        default=None,
        description="Bounded snippet extract for model context when full artifacts are omitted from payload.",
    )
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
            "Browser/OpenClaw-reachable preview URL when the host is public (or private fetch is "
            "explicitly allowed). Prefers KMBL_ORCHESTRATOR_PUBLIC_BASE_URL + candidate-preview, then a "
            "public build_candidate.preview_url. Omitted when only operator-local (localhost/private) "
            "URLs exist — see operator_preview_url in preview_resolution for human-local browsing."
        ),
    )
    preview_resolution: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Orchestrator preview resolution: preview_url (browser MCP), operator_preview_url (human), "
            "preview_grounding_mode (operator_local_only | browser_reachable | unavailable), "
            "preview_url_host_class, preview_grounding_reason, preview_url_browser_reachable_expected, "
            "and related flags."
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
    kmbl_interactive_lane_expectations: dict[str, Any] | None = Field(
        default=None,
        description=(
            "When the run is ``interactive_frontend_app_v1``: same structured hints as the generator "
            "``kmbl_interactive_lane_context`` so evaluation matches lane capabilities (bounded "
            "interactivity vs full product/WebGL shell)."
        ),
    )
    kmbl_reference_patterns: list[dict[str, Any]] | None = Field(
        default=None,
        description="Interactive lane: pattern entries aligned with generator payload.",
    )
    kmbl_library_compliance_hints: list[dict[str, Any]] | None = Field(
        default=None,
        description="Interactive lane: soft policy signals for evaluation awareness.",
    )
    kmbl_implementation_reference_cards: list[dict[str, Any]] | None = Field(
        default=None,
        description="Interactive lane: implementation reference cards aligned with generator payload.",
    )
    kmbl_inspiration_reference_cards: list[dict[str, Any]] | None = Field(
        default=None,
        description="Interactive lane: taste/design reference cards.",
    )
    kmbl_planner_observed_reference_cards: list[dict[str, Any]] | None = Field(
        default=None,
        description="Interactive lane: crawl-distilled observed reference cards.",
    )
    kmbl_reference_selection_meta: dict[str, Any] | None = Field(
        default=None,
        description="Interactive lane: reference selection audit/meta.",
    )
    kmbl_reference_library_version: int | None = Field(
        default=None,
        description="Bundled curated reference_library JSON version.",
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
    "KmblHabitatRuntimeInput",
    "PlannerRoleInput",
    "RoleType",
    "validate_role_input",
    "ValidationError",
]
