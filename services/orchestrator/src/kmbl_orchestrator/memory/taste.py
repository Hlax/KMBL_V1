"""Taste-style aggregation from persisted memory rows."""

from __future__ import annotations

from kmbl_orchestrator.domain import IdentityCrossRunMemoryRecord
from kmbl_orchestrator.memory.guardrails import clamp_strength, effective_strength_at_read
from kmbl_orchestrator.memory.keys import (
    KEY_AESTHETIC_TASTE,
    KEY_AGGREGATE_RUN_OUTCOME,
    KEY_LIKELY_EXPERIENCE_MODE,
    KEY_PREFERRED_EXPERIENCE_MODE,
    KEY_VISUAL_STYLE_HINTS,
)
from kmbl_orchestrator.memory.models import TasteProfileSummary
from kmbl_orchestrator.config import Settings


def _category_priority(cat: str) -> int:
    return {"operator_confirmed": 3, "identity_derived": 2, "run_outcome": 1}.get(cat, 0)


def build_taste_profile(
    rows: list[IdentityCrossRunMemoryRecord],
    settings: Settings,
) -> TasteProfileSummary:
    """Merge rows into a compact summary; operator_confirmed wins conflicts."""
    modes: dict[str, tuple[float, str, int]] = {}
    conflicts: list[str] = []
    themes: set[str] = set()
    tones: set[str] = set()
    visuals: set[str] = set()
    mut_hist: dict[str, float] = {}
    avoid: list[str] = []
    op_mode: str | None = None
    op_str: float | None = None

    for r in rows:
        eff = effective_strength_at_read(r.strength, r.updated_at, settings)
        pri = _category_priority(r.category)

        if r.memory_key == KEY_PREFERRED_EXPERIENCE_MODE and r.category == "operator_confirmed":
            pm = r.payload_json.get("experience_mode")
            if isinstance(pm, str) and pm.strip():
                op_mode = pm.strip()
                op_str = eff

        if r.memory_key == KEY_LIKELY_EXPERIENCE_MODE or r.memory_key == KEY_PREFERRED_EXPERIENCE_MODE:
            m = r.payload_json.get("experience_mode")
            if isinstance(m, str) and m.strip():
                key = m.strip()
                prev = modes.get(key)
                if prev is None or eff > prev[0] or (
                    eff == prev[0] and pri > prev[2]
                ):
                    if prev is not None and prev[1] != key and eff >= prev[0] * 0.9:
                        conflicts.append(
                            f"experience_mode:{key}@{r.category} vs {prev[1]}@{prev[2]}"
                        )
                    modes[key] = (eff, key, pri)

        if r.memory_key == KEY_VISUAL_STYLE_HINTS:
            for t in r.payload_json.get("themes") or []:
                if isinstance(t, str):
                    themes.add(t)
            for t in r.payload_json.get("tone") or []:
                if isinstance(t, str):
                    tones.add(t)
            for t in r.payload_json.get("visual_tendencies") or []:
                if isinstance(t, str):
                    visuals.add(t)

        if r.memory_key == KEY_AESTHETIC_TASTE:
            for t in r.payload_json.get("themes") or []:
                if isinstance(t, str):
                    themes.add(t)
            for t in r.payload_json.get("tone") or []:
                if isinstance(t, str):
                    tones.add(t)

        if r.memory_key == KEY_AGGREGATE_RUN_OUTCOME:
            pj = r.payload_json
            mh = pj.get("mutation_style_histogram") or {}
            if isinstance(mh, dict):
                for k, v in mh.items():
                    if isinstance(k, str) and isinstance(v, (int, float)):
                        mut_hist[k] = mut_hist.get(k, 0.0) + float(v) * eff
            for ap in pj.get("avoid_patterns") or []:
                if isinstance(ap, str) and ap not in avoid:
                    avoid.append(ap)

    favored_modes = sorted(
        ((m[1], m[0]) for m in modes.values()),
        key=lambda x: x[1],
        reverse=True,
    )[:5]

    if op_mode:
        # Ensure operator mode appears first with boosted display strength
        eff_op = clamp_strength(op_str or 1.0)
        favored_modes = [(op_mode, eff_op)] + [
            x for x in favored_modes if x[0] != op_mode
        ]

    return TasteProfileSummary(
        favored_experience_modes=favored_modes,
        favored_themes=sorted(themes)[:12],
        favored_tone_labels=sorted(tones)[:12],
        visual_tendencies=sorted(visuals)[:12],
        mutation_style_distribution=mut_hist,
        avoid_patterns=avoid[:12],
        conflicts_resolved=conflicts[:8],
        operator_confirmed_experience_mode=op_mode,
        operator_confirmed_strength=op_str,
    )


def taste_summary_to_prompt_hints(summary: TasteProfileSummary) -> list[str]:
    """Short human-readable lines for planner payload."""
    lines: list[str] = []
    if summary.operator_confirmed_experience_mode:
        lines.append(
            f"Operator-confirmed preference: experience_mode={summary.operator_confirmed_experience_mode} "
            f"(strength≈{summary.operator_confirmed_strength or 0:.2f})"
        )
    elif summary.favored_experience_modes:
        top = summary.favored_experience_modes[0]
        lines.append(
            f"Cross-run memory suggests prior runs favored experience_mode={top[0]} (weight≈{top[1]:.2f})."
        )
    if summary.avoid_patterns:
        lines.append("Patterns to avoid (from prior runs): " + "; ".join(summary.avoid_patterns[:4]))
    return lines
