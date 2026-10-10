from datetime import date

import pytest

from citedesk.service import DailyBudget, RateLimiter
from citedesk.service import limits as limits_module
from citedesk.service.limits import utc_today


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_key_may_burst_up_to_its_allowance_and_then_has_to_wait() -> None:
    clock = Clock()
    limiter = RateLimiter(3, clock=clock)

    assert [limiter.wait("a") for _ in range(3)] == [0.0, 0.0, 0.0]
    assert limiter.wait("a") == pytest.approx(20.0)


def test_the_allowance_comes_back_evenly_over_the_minute() -> None:
    clock = Clock()
    limiter = RateLimiter(3, clock=clock)
    for _ in range(3):
        limiter.wait("a")

    clock.now += 5
    assert limiter.wait("a") == pytest.approx(15.0)
    clock.now += 15
    assert limiter.wait("a") == 0.0
    assert limiter.wait("a") == pytest.approx(20.0)


def test_a_refused_request_takes_nothing() -> None:
    clock = Clock()
    limiter = RateLimiter(1, clock=clock)
    limiter.wait("a")

    assert [limiter.wait("a") for _ in range(5)][-1] == pytest.approx(60.0)
    clock.now += 60
    assert limiter.wait("a") == 0.0


def test_the_allowance_never_grows_beyond_a_minute() -> None:
    clock = Clock()
    limiter = RateLimiter(2, clock=clock)
    limiter.wait("a")

    clock.now += 3600
    assert [limiter.wait("a") for _ in range(3)] == [0.0, 0.0, pytest.approx(30.0)]


def test_each_key_has_its_own_allowance() -> None:
    limiter = RateLimiter(1, clock=Clock())

    assert limiter.wait("a") == 0.0
    assert limiter.wait("b") == 0.0
    assert limiter.wait("a") > 0


def test_quiet_keys_are_forgotten_and_busy_ones_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(limits_module, "_KEYS_BEFORE_CLEANUP", 3)
    clock = Clock()
    limiter = RateLimiter(1, clock=clock)
    limiter.wait("quiet-1")
    limiter.wait("quiet-2")
    clock.now += 60
    limiter.wait("busy")

    assert limiter.wait("new") == 0.0

    assert limiter.wait("busy") > 0
    assert limiter.wait("quiet-1") == 0.0


class Calendar:
    def __init__(self) -> None:
        self.day = date(2026, 10, 10)

    def __call__(self) -> date:
        return self.day


def test_the_budget_is_exhausted_once_the_day_has_cost_it() -> None:
    budget = DailyBudget(1.0, today=Calendar())

    budget.spend(0.6)
    assert (budget.spent, budget.exhausted) == (0.6, False)
    budget.spend(0.4)
    assert (budget.spent, budget.exhausted) == (1.0, True)


def test_a_new_day_starts_from_zero() -> None:
    calendar = Calendar()
    budget = DailyBudget(1.0, today=calendar)
    budget.spend(2.0)

    calendar.day = date(2026, 10, 11)

    assert (budget.spent, budget.exhausted) == (0.0, False)
    budget.spend(0.25)
    assert budget.spent == 0.25


def test_days_are_counted_in_utc() -> None:
    assert isinstance(utc_today(), date)
    assert not DailyBudget(1.0).exhausted
