"""
Rolling one-hour token budget for KMBL-routed OpenAI image-generation generator calls.

Conservative accounting: uses estimated tokens per invocation (see Settings).

**Process-local:** usage resets on process restart; multi-instance deployments may
over-consume relative to a global cap until a shared backend exists. The
``OpenAIImageBudgetStore`` protocol is intentionally narrow so **Redis/Postgres**
(or another store) can back ``try_consume`` later for cross-process correctness—
not implemented in this pass.

Inject ``now_fn`` (or pass ``now`` per call) so tests do not depend on wall-clock time.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Callable, Deque, Protocol, Tuple, runtime_checkable

_LOG = logging.getLogger(__name__)

DEFAULT_HOURLY_TOKEN_CAP = 1_500_000

NowFn = Callable[[], datetime]


@dataclass(frozen=True)
class BudgetDecision:
    """Result of a budget reservation attempt."""

    allowed: bool
    used_tokens_after: int
    requested_tokens: int
    cap_tokens: int
    remaining_tokens_after: int
    denial_reason: str | None


@runtime_checkable
class OpenAIImageBudgetStore(Protocol):
    """Minimal budget API for generator OpenAI routing (swappable in-memory / future Redis/DB)."""

    @property
    def cap_tokens(self) -> int: ...

    def usage_in_window(self, now: datetime | None = None) -> int: ...

    def try_consume(self, tokens: int, *, now: datetime | None = None) -> BudgetDecision: ...


def check_or_consume_openai_image_budget(
    store: OpenAIImageBudgetStore,
    tokens: int,
    *,
    now: datetime | None = None,
) -> BudgetDecision:
    """Thin wrapper for routing code and tests."""
    return store.try_consume(tokens, now=now)


class OpenAIHourlyBudgetGuard:
    """
    Sliding 60-minute window of ``(utc_timestamp, tokens)``.

    Implements ``OpenAIImageBudgetStore``. Thread-safe for a single process.
    """

    def __init__(
        self,
        hourly_cap: int,
        *,
        now_fn: NowFn | None = None,
    ) -> None:
        self._cap = max(0, int(hourly_cap))
        self._window: Deque[Tuple[datetime, int]] = deque()
        self._lock = Lock()
        self._now_fn: NowFn = now_fn or (lambda: datetime.now(timezone.utc))

    @property
    def cap(self) -> int:
        return self._cap

    @property
    def cap_tokens(self) -> int:
        return self._cap

    def _resolve_now(self, now: datetime | None) -> datetime:
        return now if now is not None else self._now_fn()

    def _prune(self, now: datetime) -> int:
        cutoff = now - timedelta(hours=1)
        while self._window and self._window[0][0] < cutoff:
            self._window.popleft()
        total = 0
        for _, t in self._window:
            total += t
        return total

    def usage_in_window(self, now: datetime | None = None) -> int:
        n = self._resolve_now(now)
        with self._lock:
            return self._prune(n)

    def try_consume(self, tokens: int, *, now: datetime | None = None) -> BudgetDecision:
        n = self._resolve_now(now)
        if self._cap <= 0:
            return BudgetDecision(
                allowed=False,
                used_tokens_after=0,
                requested_tokens=max(0, int(tokens)),
                cap_tokens=self._cap,
                remaining_tokens_after=0,
                denial_reason="hourly_token_cap_zero",
            )
        t = max(0, int(tokens))
        if t <= 0:
            used = self.usage_in_window(n)
            rem = max(0, self._cap - used)
            return BudgetDecision(
                allowed=True,
                used_tokens_after=used,
                requested_tokens=0,
                cap_tokens=self._cap,
                remaining_tokens_after=rem,
                denial_reason=None,
            )
        with self._lock:
            used = self._prune(n)
            if used + t > self._cap:
                rem = max(0, self._cap - used)
                _LOG.warning(
                    "openai_hourly_budget deny need=%s used=%s cap=%s remaining=%s",
                    t,
                    used,
                    self._cap,
                    rem,
                )
                return BudgetDecision(
                    allowed=False,
                    used_tokens_after=used,
                    requested_tokens=t,
                    cap_tokens=self._cap,
                    remaining_tokens_after=rem,
                    denial_reason="hourly_token_budget_exhausted",
                )
            self._window.append((n, t))
            new_used = used + t
            rem_after = max(0, self._cap - new_used)
            _LOG.info(
                "openai_hourly_budget consume tokens=%s used=%s cap=%s remaining=%s",
                t,
                new_used,
                self._cap,
                rem_after,
            )
            return BudgetDecision(
                allowed=True,
                used_tokens_after=new_used,
                requested_tokens=t,
                cap_tokens=self._cap,
                remaining_tokens_after=rem_after,
                denial_reason=None,
            )

    def reset_for_tests(self) -> None:
        with self._lock:
            self._window.clear()


_guard_singleton: OpenAIHourlyBudgetGuard | None = None


def get_openai_hourly_budget_guard(hourly_cap: int | None = None) -> OpenAIHourlyBudgetGuard:
    """Process-wide guard; cap fixed at first call unless tests reset."""
    global _guard_singleton
    if _guard_singleton is None:
        _guard_singleton = OpenAIHourlyBudgetGuard(
            hourly_cap if hourly_cap is not None else DEFAULT_HOURLY_TOKEN_CAP,
        )
    return _guard_singleton


def reset_openai_hourly_budget_guard_for_tests() -> None:
    global _guard_singleton
    _guard_singleton = None


__all__ = [
    "DEFAULT_HOURLY_TOKEN_CAP",
    "BudgetDecision",
    "OpenAIImageBudgetStore",
    "OpenAIHourlyBudgetGuard",
    "check_or_consume_openai_image_budget",
    "get_openai_hourly_budget_guard",
    "reset_openai_hourly_budget_guard_for_tests",
]
