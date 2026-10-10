"""The service's own limits: how often it may be asked and what a day may cost."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# Above this many keys, the buckets of clients that have gone quiet are dropped.
_KEYS_BEFORE_CLEANUP = 10_000


class RateLimiter:
    """At most so many requests a minute for each key, as token buckets.

    A key starts with a full minute's allowance, so a short burst is let through, and
    earns it back evenly over the minute.
    """

    def __init__(self, per_minute: int, *, clock: Callable[[], float] = time.monotonic) -> None:
        """Set the allowance.

        Args:
            per_minute: How many requests a key may make in a minute.
            clock: Returns the time in seconds. Tests replace it.
        """
        self._capacity = float(per_minute)
        self._per_second = per_minute / 60
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}

    def wait(self, key: str) -> float:
        """Take one request from a key's allowance.

        Returns:
            0 when the request may go ahead. Otherwise the seconds until the key may ask
            again, and nothing is taken.
        """
        now = self._clock()
        tokens = self._tokens(key, now)
        if tokens < 1:
            return (1 - tokens) / self._per_second
        if len(self._buckets) >= _KEYS_BEFORE_CLEANUP:
            self._forget_full(now)
        self._buckets[key] = (tokens - 1, now)
        return 0.0

    def _tokens(self, key: str, now: float) -> float:
        """Count what a key has left, with what it earned back since its last request."""
        tokens, updated = self._buckets.get(key, (self._capacity, now))
        return min(self._capacity, tokens + (now - updated) * self._per_second)

    def _forget_full(self, now: float) -> None:
        """Drop the keys whose allowance is whole again: forgetting them changes nothing."""
        full = [key for key in self._buckets if self._tokens(key, now) >= self._capacity]
        for key in full:
            del self._buckets[key]


def utc_today() -> date:
    """Return the current day in UTC."""
    return datetime.now(UTC).date()


class DailyBudget:
    """What the model may cost in one day, counted in UTC days.

    It lives in memory: it starts again when the service restarts, and two processes would
    each keep their own. The provider's spend limit is the backstop for both cases.
    """

    def __init__(self, usd: float, *, today: Callable[[], date] = utc_today) -> None:
        """Set the day's budget.

        Args:
            usd: What a day may cost, in US dollars.
            today: Returns the current day. Tests replace it.
        """
        self._usd = usd
        self._today = today
        self._day = today()
        self._spent = 0.0

    @property
    def spent(self) -> float:
        """What today has cost so far, in US dollars."""
        self._roll()
        return self._spent

    @property
    def exhausted(self) -> bool:
        """Whether today's budget is gone."""
        return self.spent >= self._usd

    def spend(self, usd: float) -> None:
        """Add the cost of one model call to today's total."""
        self._roll()
        self._spent += usd

    def _roll(self) -> None:
        """Start from zero when the day has changed."""
        today = self._today()
        if today != self._day:
            self._day = today
            self._spent = 0.0
