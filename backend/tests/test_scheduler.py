import asyncio

from ingestion.scheduler import run_periodically


async def test_job_repeats_and_stops_on_request() -> None:
    calls = 0

    async def job() -> None:
        nonlocal calls
        calls += 1

    stop = asyncio.Event()
    task = asyncio.create_task(run_periodically(job, 0.01, stop))
    await asyncio.sleep(0.12)
    stop.set()
    await task
    assert calls >= 3


async def test_a_failing_run_does_not_end_the_loop() -> None:
    calls = 0

    async def job() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")

    stop = asyncio.Event()
    task = asyncio.create_task(run_periodically(job, 0.01, stop))
    await asyncio.sleep(0.12)
    stop.set()
    await task
    assert calls >= 2


    