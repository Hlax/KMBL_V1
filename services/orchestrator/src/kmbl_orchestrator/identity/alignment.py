"""
Identity alignment scoring — orchestrator-side computation.

The evaluator agent produces an ``alignment_report`` block in its output metrics.
This module:
  1. Extracts that block from raw evaluator output
  2. Computes a normalized 0-1 alignment score from it
  3. Provides an orchestrator-side fallback that scores from artifact content
     when the evaluator didn't produce an alignment_report

The score is the single most important signal added by this fix:
  - It makes the ``auto_publish_threshold`` meaningful
  - It enables the decision_router to detect alignment regression across iterations
  - It populates ``AutonomousLoopRecord.last_evaluator_score``

Score components and weights:
  - must_mention_hit_rate:  0.40  (identity-critical strings present in output)
  - palette_used:           0.25  (at least one palette color referenced)
  - tone_reflected:         0.20  (tone keywords present in text copy)
  - structural_present:     0.15  (basic structure: name/role/bio somewhere)

A score of 0.0 means the output has no relationship to the identity.
A score of 1.0 means all must_mention items present, palette used, tone matches.
"""

from __future__ import annotations

import logging
import re
from typing import Any

_log = logging.getLogger(__name__)

# Score weights — must sum to 1.0
_W_MUST_MENTION = 0.40
_W_PALETTE = 0.25
_W_TONE = 0.20
_W_STRUCTURAL = 0.15


def extract_alignment_report_from_metrics(
    metrics: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Extract the alignment_report block from evaluator metrics.

    Expected evaluator output shape (in metrics):
    {
      "alignment_report": {
        "must_mention_hits": ["John Doe", "photographer"],   # found
        "must_mention_misses": ["Abstract Studio"],           # not found
        "palette_colors_found": ["#1a1a1a", "#ff6b35"],
        "palette_colors_missing": [],
        "tone_keywords_reflected": ["minimal", "bold"],
        "tone_keywords_missing": ["warm"],
        "name_present": true,
        "role_present": true,
        "bio_excerpt_present": false,
        "evaluator_notes": "Good palette use, missing bio reference"
      }
    }

    Returns None if no alignment_report block.
    """
    if not isinstance(metrics, dict):
        return None
    ar = metrics.get("alignment_report")
    if not isinstance(ar, dict):
        return None
    return ar


def compute_alignment_score_from_report(
    alignment_report: dict[str, Any],
    identity_brief: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    """
    Compute a 0-1 alignment score from an evaluator-produced alignment_report.

    Returns (score, signals_dict) where signals_dict contains per-criterion details.

    This is the primary path when the evaluator produced alignment_report.
    """
    signals: dict[str, Any] = {}
    total = 0.0

    # --- must_mention hit rate (0.40 weight) ---
    must_mention: list[str] = identity_brief.get("must_mention") or []
    if must_mention:
        hits: list[str] = alignment_report.get("must_mention_hits") or []
        misses: list[str] = alignment_report.get("must_mention_misses") or []
        hit_count = len(hits)
        total_count = len(hits) + len(misses)
        if total_count == 0:
            # evaluator didn't check — infer from must_mention list length
            hit_rate = 0.5  # assume partial
        else:
            hit_rate = hit_count / total_count
        signals["must_mention_hit_rate"] = round(hit_rate, 3)
        signals["must_mention_hits"] = hits
        signals["must_mention_misses"] = misses
        total += _W_MUST_MENTION * hit_rate
    else:
        # No must_mention items — this criterion is N/A; redistribute weight
        signals["must_mention_hit_rate"] = None
        total += _W_MUST_MENTION * 0.8  # default partial credit

    # --- palette used (0.25 weight) ---
    palette_hex: list[str] = identity_brief.get("palette_hex") or []
    if palette_hex:
        colors_found: list[str] = alignment_report.get("palette_colors_found") or []
        palette_score = 1.0 if colors_found else 0.0
        # Partial credit: more colors used = better
        if colors_found and len(palette_hex) > 0:
            palette_score = min(1.0, len(colors_found) / max(1, min(3, len(palette_hex))))
        signals["palette_used"] = bool(colors_found)
        signals["palette_colors_found"] = colors_found
        signals["palette_colors_missing"] = alignment_report.get("palette_colors_missing") or []
        total += _W_PALETTE * palette_score
    else:
        signals["palette_used"] = None
        total += _W_PALETTE * 0.8  # N/A partial credit

    # --- tone reflected (0.20 weight) ---
    tone_keywords: list[str] = identity_brief.get("tone_keywords") or []
    if tone_keywords:
        tone_reflected: list[str] = alignment_report.get("tone_keywords_reflected") or []
        tone_missing: list[str] = alignment_report.get("tone_keywords_missing") or []
        tone_total = len(tone_reflected) + len(tone_missing)
        if tone_total == 0:
            tone_rate = 0.5
        else:
            tone_rate = len(tone_reflected) / tone_total
        signals["tone_reflected_rate"] = round(tone_rate, 3)
        signals["tone_keywords_reflected"] = tone_reflected
        total += _W_TONE * tone_rate
    else:
        signals["tone_reflected_rate"] = None
        total += _W_TONE * 0.8

    # --- structural presence (0.15 weight) ---
    name_present = bool(alignment_report.get("name_present"))
    role_present = bool(alignment_report.get("role_present"))
    bio_present = bool(alignment_report.get("bio_excerpt_present"))
    structural_checks = [
        name_present,
        role_present,
    ]
    if identity_brief.get("short_bio"):
        structural_checks.append(bio_present)
    structural_score = sum(structural_checks) / max(1, len(structural_checks))
    signals["name_present"] = name_present
    signals["role_present"] = role_present
    signals["bio_present"] = bio_present
    signals["structural_score"] = round(structural_score, 3)
    total += _W_STRUCTURAL * structural_score

    signals["evaluator_notes"] = alignment_report.get("evaluator_notes", "")
    signals["source"] = "evaluator_report"

    final_score = round(min(1.0, max(0.0, total)), 3)
    signals["alignment_score"] = final_score
    return final_score, signals


def compute_alignment_score_from_artifacts(
    artifact_refs: list[Any],
    identity_brief: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    """
    Fallback alignment scorer when evaluator didn't produce alignment_report.

    Scans artifact content (HTML text) for must_mention strings and palette colors.
    This is less accurate than evaluator-reported alignment but ensures the score
    is never None even when the evaluator agent fails to produce the block.

    Returns (score, signals_dict).
    """
    signals: dict[str, Any] = {"source": "orchestrator_fallback"}
    total = 0.0

    # Collect all text content from HTML artifacts
    all_text = _extract_text_from_artifacts(artifact_refs)

    # --- must_mention ---
    must_mention: list[str] = identity_brief.get("must_mention") or []
    if must_mention:
        hits = [m for m in must_mention if m.lower() in all_text.lower()]
        hit_rate = len(hits) / len(must_mention)
        signals["must_mention_hit_rate"] = round(hit_rate, 3)
        signals["must_mention_hits"] = hits
        signals["must_mention_misses"] = [m for m in must_mention if m not in hits]
        total += _W_MUST_MENTION * hit_rate
    else:
        signals["must_mention_hit_rate"] = None
        total += _W_MUST_MENTION * 0.7

    # --- palette ---
    palette_hex: list[str] = identity_brief.get("palette_hex") or []
    if palette_hex:
        colors_found = [c for c in palette_hex if c.lower() in all_text.lower()]
        palette_score = min(1.0, len(colors_found) / max(1, min(3, len(palette_hex))))
        signals["palette_used"] = bool(colors_found)
        signals["palette_colors_found"] = colors_found
        total += _W_PALETTE * palette_score
    else:
        signals["palette_used"] = None
        total += _W_PALETTE * 0.7

    # --- tone (keyword scan in text) ---
    tone_keywords: list[str] = identity_brief.get("tone_keywords") or []
    if tone_keywords and all_text:
        reflected = [kw for kw in tone_keywords if kw.lower() in all_text.lower()]
        tone_rate = len(reflected) / len(tone_keywords)
        signals["tone_reflected_rate"] = round(tone_rate, 3)
        total += _W_TONE * tone_rate
    else:
        signals["tone_reflected_rate"] = None
        total += _W_TONE * 0.6

    # --- structural (name/role present) ---
    display_name = (identity_brief.get("display_name") or "").lower()
    role = (identity_brief.get("role_or_title") or "").lower()
    text_lower = all_text.lower()
    name_present = bool(display_name) and display_name in text_lower
    role_present = bool(role) and role in text_lower
    structural_checks = [name_present, role_present]
    structural_score = sum(structural_checks) / max(1, len(structural_checks))
    signals["name_present"] = name_present
    signals["role_present"] = role_present
    signals["structural_score"] = round(structural_score, 3)
    total += _W_STRUCTURAL * structural_score

    final_score = round(min(1.0, max(0.0, total)), 3)
    signals["alignment_score"] = final_score
    return final_score, signals


def _extract_text_from_artifacts(artifact_refs: list[Any]) -> str:
    """Extract all text content from artifact_refs for scanning."""
    chunks: list[str] = []
    for ref in artifact_refs:
        if not isinstance(ref, dict):
            continue
        content = ref.get("content", "")
        if isinstance(content, str) and content:
            # Strip HTML tags for text scanning
            stripped = re.sub(r"<[^>]+>", " ", content)
            chunks.append(stripped)
    return " ".join(chunks)


def score_alignment(
    *,
    metrics: dict[str, Any],
    artifact_refs: list[Any],
    identity_brief: dict[str, Any] | None,
) -> tuple[float | None, dict[str, Any]]:
    """
    Primary entry point: compute alignment score from evaluator output.

    Tries evaluator-reported alignment_report first; falls back to artifact scan.
    Returns (score, signals) or (None, {}) when no identity_brief.

    Args:
        metrics: evaluator metrics dict (may contain alignment_report)
        artifact_refs: normalized artifact refs from build candidate
        identity_brief: the identity brief dict injected into the run (may be None)
    """
    if not identity_brief:
        return None, {}

    # Path 1: evaluator produced alignment_report — authoritative
    ar = extract_alignment_report_from_metrics(metrics)
    if ar:
        score, signals = compute_alignment_score_from_report(ar, identity_brief)
        _log.info(
            "alignment_score source=evaluator_report score=%.3f "
            "must_mention_hit_rate=%s palette_used=%s",
            score,
            signals.get("must_mention_hit_rate"),
            signals.get("palette_used"),
        )
        return score, signals

    # Path 2: no alignment_report from evaluator — fallback to artifact scan
    _log.info(
        "alignment_score source=orchestrator_fallback "
        "(evaluator did not produce alignment_report)"
    )
    score, signals = compute_alignment_score_from_artifacts(artifact_refs, identity_brief)
    _log.info(
        "alignment_score source=orchestrator_fallback score=%.3f "
        "must_mention_hit_rate=%s palette_used=%s",
        score,
        signals.get("must_mention_hit_rate"),
        signals.get("palette_used"),
    )
    return score, signals


def compute_alignment_trend(
    history: list[dict[str, Any]],
) -> str:
    """
    Compute alignment trend label from score history.

    history: list of {"iteration_index": int, "score": float} dicts, oldest first.

    Returns one of: "improving" | "regressing" | "plateau" | "insufficient_data"
    """
    scores = [
        float(h["score"])
        for h in history
        if isinstance(h.get("score"), (int, float))
    ]
    if len(scores) < 2:
        return "insufficient_data"
    if len(scores) == 2:
        delta = scores[-1] - scores[-2]
        if delta > 0.05:
            return "improving"
        if delta < -0.05:
            return "regressing"
        return "plateau"
    # Use last 3
    recent = scores[-3:]
    avg_delta = (recent[-1] - recent[0]) / (len(recent) - 1)
    if avg_delta > 0.04:
        return "improving"
    if avg_delta < -0.04:
        return "regressing"
    return "plateau"


def select_retry_direction(
    *,
    alignment_score: float | None,
    alignment_trend: str,
    evaluator_status: str,
    iteration_index: int,
    stagnation_count: int,
    prior_direction: str | None,
) -> str:
    """
    Orchestrator-owned direction selection for iteration retry.

    This is deterministic logic in the orchestrator — not a suggestion to the planner.
    The planner receives this direction in retry_context and MUST act on it.

    Returns one of:
      "refine"         — address specific issues, keep visual direction
      "pivot_layout"   — change layout structure significantly
      "pivot_palette"  — keep content/layout, change color scheme
      "pivot_content"  — keep structure, rewrite copy/sections
      "fresh_start"    — discard everything, start from identity brief only

    Selection logic:
      - If alignment improving + evaluator partial → refine
      - If alignment plateau/regressing + palette_used False → pivot_palette
      - If stagnation >= 3 → fresh_start
      - If evaluator fail → pivot_layout (structural problem)
      - If iteration >= 2 and still low alignment → escalate direction
      - Default → refine
    """
    # Stagnation overrides everything
    if stagnation_count >= 3:
        return "fresh_start"

    # Evaluator hard fail → structural pivot
    if evaluator_status == "fail":
        if iteration_index == 0:
            return "pivot_layout"
        # Second fail: escalate to fresh start
        return "fresh_start"

    # Alignment is available and meaningful
    if alignment_score is not None:
        if alignment_trend == "regressing":
            # Something is actively getting worse
            if prior_direction == "pivot_palette":
                return "pivot_content"
            if prior_direction == "pivot_layout":
                return "fresh_start"
            return "pivot_palette"

        if alignment_trend == "plateau":
            # Stuck — rotate the dimension we're changing
            rotation = {
                None: "pivot_layout",
                "refine": "pivot_layout",
                "pivot_layout": "pivot_palette",
                "pivot_palette": "pivot_content",
                "pivot_content": "fresh_start",
            }
            return rotation.get(prior_direction, "pivot_layout")

        if alignment_trend == "improving":
            return "refine"

    # Default: try to refine first
    return "refine"
