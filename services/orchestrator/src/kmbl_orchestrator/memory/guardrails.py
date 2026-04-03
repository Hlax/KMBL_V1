"""Strength clamps and merge limits for cross-run memory."""

from __future__ import annotations

from datetime import datetime, timezone
from kmbl_orchestrator.config import Settings


def clamp_strength(x: float, *, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def effective_strength_at_read(
    stored_strength: float,
    updated_at_iso: str | None,
    settings: Settings,
) -> float:
    """Reduce influence of stale rows (simple half-life)."""
    if not updated_at_iso:
        return clamp_strength(stored_strength)
    try:
        u = datetime.fromisoformat(updated_at_iso.replace("Z", "+00:00"))
    except ValueError:
        return clamp_strength(stored_strength)
    now = datetime.now(timezone.utc)
    if u.tzinfo is None:
        u = u.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - u).total_seconds() / 86400.0)
    half = float(settings.memory_freshness_half_life_days)
    if half <= 0:
        return clamp_strength(stored_strength)
    # decay: 0.5^(age/half) — at one half-life, strength halves
    import math

    factor = math.pow(0.5, age_days / half)
    return clamp_strength(stored_strength * factor)


def cap_delta_negative(delta: float, *, floor: float = -0.15) -> float:
    """Single failed run cannot dominate."""
    return max(floor, delta)


def cap_delta_positive(delta: float, *, ceiling: float = 0.12) -> float:
    """Gradual learning."""
    return min(ceiling, delta)


def merge_histogram(
    hist: dict[str, Any],
    key: str,
    inc: float = 1.0,
) -> dict[str, Any]:
    out = dict(hist)
    cur = float(out.get(key, 0) or 0)
    out[key] = cur + inc
    return out

