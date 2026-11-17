import asyncio

from domain.tracing import finish_trace, span, start_trace


def test_span_without_a_trace_is_a_noop() -> None:
    with span("anything"):
        pass


async def test_spans_accumulate_by_name() -> None:
    trace, token = start_trace()
    try:
        for _ in range(2):
            with span("work"):
                await asyncio.sleep(0.01)
    finally:
        finish_trace(token)
    assert trace.stages["work"] >= 15


async def test_parallel_tasks_write_to_the_same_trace() -> None:
    async def stage(name: str) -> None:
        with span(name):
            await asyncio.sleep(0.02)

    trace, token = start_trace()
    try:
        await asyncio.gather(stage("a"), stage("b"))
    finally:
        finish_trace(token)
    assert set(trace.stages) == {"a", "b"}


    