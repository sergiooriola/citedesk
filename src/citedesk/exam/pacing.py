"""How the calls of an exam are sent: the first alone, the rest a few at a time."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence


async def first_then_rest[Result](
    jobs: Sequence[Callable[[], Awaitable[Result]]], concurrency: int
) -> list[Result]:
    """Run the jobs and return their results in the order of the jobs.

    The first job runs alone: the provider caches the instructions once the first response
    begins, and jobs sent before that would each pay for writing them. The rest run with at
    most `concurrency` in flight.
    """
    if not jobs:
        return []
    limit = asyncio.Semaphore(concurrency)

    async def bounded(job: Callable[[], Awaitable[Result]]) -> Result:
        async with limit:
            return await job()

    first = await bounded(jobs[0])
    async with asyncio.TaskGroup() as group:
        rest = [group.create_task(bounded(job)) for job in jobs[1:]]
    return [first, *(task.result() for task in rest)]
