"""Pydantic read models for cross-run memory (operator + planner surfaces)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryReadTrace(BaseModel):
    """What was loaded for a run (inspectable)."""

    identity_id: str
    memory_keys_read: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    provenance_notes: list[str] = Field(default_factory=list)


class MemoryWriteTrace(BaseModel):
    """What was written or updated (inspectable)."""

    identity_id: str
    memory_keys_written: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    source_graph_run_id: str | None = None
    provenance_notes: list[str] = Field(default_factory=list)


class TasteProfileSummary(BaseModel):
    """Compact aggregate for planner bias — not a recommendation engine."""

    favored_experience_modes: list[tuple[str, float]] = Field(
        default_factory=list,
        description="(mode, effective_strength) sorted by strength desc.",
    )
    favored_themes: list[str] = Field(default_factory=list)
    favored_tone_labels: list[str] = Field(default_factory=list)
    visual_tendencies: list[str] = Field(default_factory=list)
    mutation_style_distribution: dict[str, float] = Field(default_factory=dict)
    avoid_patterns: list[str] = Field(default_factory=list)
    conflicts_resolved: list[str] = Field(default_factory=list)
    operator_confirmed_experience_mode: str | None = None
    operator_confirmed_strength: float | None = None

