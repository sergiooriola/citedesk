import asyncio
from functools import partial

from citedesk.exam.pacing import first_then_rest


class Load:
    """Counts how many jobs are in flight and how many were when the first one ended."""

    def __init__(self) -> None:
        self.in_flight = 0
        self.most_in_flight = 0
        self.in_flight_when_first_ended: int | None = None

    async def job(self, number: int) -> int:
        self.in_flight += 1
        self.most_in_flight = max(self.most_in_flight, self.in_flight)
        await asyncio.sleep(0)
        if self.in_flight_when_first_ended is None:
            self.in_flight_when_first_ended = self.in_flight
        self.in_flight -= 1
        return number * 10


def test_results_come_back_in_the_order_of_the_jobs() -> None:
    load = Load()

    results = asyncio.run(first_then_rest([partial(load.job, n) for n in range(6)], 3))

    assert results == [0, 10, 20, 30, 40, 50]


def test_the_first_job_runs_alone_and_the_rest_within_the_limit() -> None:
    load = Load()

    asyncio.run(first_then_rest([partial(load.job, n) for n in range(6)], 2))

    assert load.in_flight_when_first_ended == 1
    assert load.most_in_flight == 2


def test_no_jobs_give_no_results() -> None:
    assert asyncio.run(first_then_rest([], 4)) == []
