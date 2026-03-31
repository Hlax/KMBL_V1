"""Working staging facts: structured context for generator/evaluator handoff.

Provides a compact, typed summary of the current working staging surface
so agents can reason about amendments rather than regenerating blindly.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from kmbl_orchestrator.domain import WorkingStagingRecord


class ArtifactInventory(BaseModel):
    """Summary of artifacts in the current working staging surface."""

    total_count: int = 0
    by_role: dict[str, int] = Field(default_factory=dict)
    has_static_frontend: bool = False
    has_previewable_html: bool = False
    file_paths: list[str] = Field(default_factory=list)


class CheckpointAvailability(BaseModel):
    """Checkpoint recovery information."""

    has_checkpoints: bool = False
    checkpoint_count: int = 0
    latest_checkpoint_revision: int | None = None
    latest_checkpoint_trigger: str | None = None


class RecentEvaluatorSummary(BaseModel):
    """Summary of recent evaluator state for amendment context."""

    status: str | None = None
    issue_count: int = 0
    issue_hints: list[str] = Field(default_factory=list)
    metrics_summary: dict[str, Any] = Field(default_factory=dict)


class PressureSummary(BaseModel):
    """Condensed pressure state for agent awareness."""

    pressure_score: float = 0.0
    recommendation: Literal["patch", "rebuild", "neutral"] = "neutral"
    key_concerns: list[str] = Field(default_factory=list)


class RevisionHistorySummary(BaseModel):
    """Condensed revision history for amendment context."""

    current_revision: int = 0
    patches_since_rebuild: int = 0
    last_update_mode: str = "init"
    stagnation_count: int = 0


class WorkingStagingFacts(BaseModel):
    """Structured summary of working staging surface for agent handoff.

    Designed to be compact and extensible — agents receive enough context
    to make informed amendment decisions without massive raw payload dumps.
    """

    working_staging_id: str
    thread_id: str
    identity_id: str | None = None

    revision_history: RevisionHistorySummary
    artifact_inventory: ArtifactInventory
    checkpoint_availability: CheckpointAvailability
    recent_evaluator: RecentEvaluatorSummary | None = None
    pressure_summary: PressureSummary | None = None

    surface_status: Literal["draft", "review_ready", "frozen"] = "draft"
    is_empty: bool = True
    can_patch: bool = False
    needs_rebuild: bool = True

    # Set during multi-iteration loop to provide fresh context
    iteration_context: dict[str, Any] | None = None


def build_working_staging_facts(
    working_staging: WorkingStagingRecord | None,
    *,
    checkpoint_count: int = 0,
    latest_checkpoint_revision: int | None = None,
    latest_checkpoint_trigger: str | None = None,
    evaluator_status: str | None = None,
    evaluator_issues: list[Any] | None = None,
    evaluator_metrics: dict[str, Any] | None = None,
    pressure_score: float = 0.0,
    pressure_recommendation: str = "neutral",
    pressure_concerns: list[str] | None = None,
    patches_since_rebuild: int = 0,
    stagnation_count: int = 0,
) -> WorkingStagingFacts:
    """Build structured facts from a working staging record and supplementary data."""
    if working_staging is None:
        return WorkingStagingFacts(
            working_staging_id="",
            thread_id="",
            revision_history=RevisionHistorySummary(),
            artifact_inventory=ArtifactInventory(),
            checkpoint_availability=CheckpointAvailability(),
            is_empty=True,
            can_patch=False,
            needs_rebuild=True,
        )

    payload = working_staging.payload_json or {}
    artifacts = payload.get("artifacts", {})
    refs = artifacts.get("artifact_refs", []) if isinstance(artifacts, dict) else []

    by_role: dict[str, int] = {}
    file_paths: list[str] = []
    has_static = False
    has_html = False

    for ref in refs:
        if not isinstance(ref, dict):
            continue
        role = ref.get("role", "unknown")
        by_role[role] = by_role.get(role, 0) + 1
        path = ref.get("path")
        if isinstance(path, str) and path.strip():
            file_paths.append(path.strip())
        if role == "static_frontend_file_v1":
            has_static = True
            if ref.get("language") == "html":
                has_html = True

    artifact_inventory = ArtifactInventory(
        total_count=len(refs),
        by_role=by_role,
        has_static_frontend=has_static,
        has_previewable_html=has_html,
        file_paths=file_paths[:20],
    )

    checkpoint_availability = CheckpointAvailability(
        has_checkpoints=checkpoint_count > 0,
        checkpoint_count=checkpoint_count,
        latest_checkpoint_revision=latest_checkpoint_revision,
        latest_checkpoint_trigger=latest_checkpoint_trigger,
    )

    recent_evaluator = None
    if evaluator_status is not None:
        issue_hints = []
        if evaluator_issues:
            for iss in evaluator_issues[:5]:
                if isinstance(iss, dict):
                    hint = iss.get("message") or iss.get("description") or str(iss.get("type", ""))
                    if isinstance(hint, str) and hint.strip():
                        issue_hints.append(hint.strip()[:100])

        recent_evaluator = RecentEvaluatorSummary(
            status=evaluator_status,
            issue_count=len(evaluator_issues) if evaluator_issues else 0,
            issue_hints=issue_hints,
            metrics_summary=_compact_metrics(evaluator_metrics) if evaluator_metrics else {},
        )

    pressure_summary = None
    if pressure_score > 0 or pressure_concerns:
        pressure_summary = PressureSummary(
            pressure_score=pressure_score,
            recommendation=pressure_recommendation,  # type: ignore[arg-type]
            key_concerns=pressure_concerns or [],
        )

    revision_history = RevisionHistorySummary(
        current_revision=working_staging.revision,
        patches_since_rebuild=patches_since_rebuild,
        last_update_mode=working_staging.last_update_mode,
        stagnation_count=stagnation_count,
    )

    is_empty = working_staging.revision == 0 or not refs
    can_patch = working_staging.revision > 0 and evaluator_status in ("pass", "partial", None)
    needs_rebuild = is_empty or evaluator_status == "fail"

    return WorkingStagingFacts(
        working_staging_id=str(working_staging.working_staging_id),
        thread_id=str(working_staging.thread_id),
        identity_id=str(working_staging.identity_id) if working_staging.identity_id else None,
        revision_history=revision_history,
        artifact_inventory=artifact_inventory,
        checkpoint_availability=checkpoint_availability,
        recent_evaluator=recent_evaluator,
        pressure_summary=pressure_summary,
        surface_status=working_staging.status,
        is_empty=is_empty,
        can_patch=can_patch,
        needs_rebuild=needs_rebuild,
    )


def working_staging_facts_to_payload(facts: WorkingStagingFacts) -> dict[str, Any]:
    """Convert facts to a dict suitable for agent payload handoff."""
    return facts.model_dump(mode="json", exclude_none=True)


def _compact_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """Extract a compact metrics summary (first 5 scalar values)."""
    out: dict[str, Any] = {}
    count = 0
    for k, v in metrics.items():
        if count >= 5:
            break
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
            count += 1
    return out
