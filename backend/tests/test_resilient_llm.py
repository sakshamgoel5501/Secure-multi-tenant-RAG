import asyncio
import time

import pytest

from adapters.resilient_llm import ResilientLLM


class Scripted:
    """Each call takes the next (delay, outcome) from the script."""

    def __init__(self, script: list[tuple[float, str | Exception]]) -> None:
        self.script = script
        self.calls = 0

    async def generate(self, system: str, user: str) -> str:
        delay, outcome = self.script[self.calls]
        self.calls += 1
        await asyncio.sleep(delay)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def test_failure_is_retried() -> None:
    inner = Scripted([(0, RuntimeError("429")), (0, "ok")])
    assert await ResilientLLM(inner, max_attempts=2, hedge_after=None).generate("s", "u") == "ok"
    assert inner.calls == 2


async def test_slow_first_call_is_beaten_by_the_hedge() -> None:
    inner = Scripted([(1.0, "slow"), (0.0, "fast")])
    started = time.perf_counter()
    result = await ResilientLLM(inner, max_attempts=2, hedge_after=0.05).generate("s", "u")
    assert result == "fast"
    assert time.perf_counter() - started < 0.5


async def test_all_attempts_failing_raises() -> None:
    inner = Scripted([(0, RuntimeError("a")), (0, RuntimeError("b"))])
    with pytest.raises(RuntimeError):
        await ResilientLLM(inner, max_attempts=2, hedge_after=None).generate("s", "u")


async def test_single_attempt_never_hedges() -> None:
    inner = Scripted([(0.1, "only")])
    assert await ResilientLLM(inner, max_attempts=1, hedge_after=0.01).generate("s", "u") == "only"
    assert inner.calls == 1


class StreamScripted:
    """Each call takes the next script: a list of pieces, ending in an exception to raise."""

    def __init__(self, script: list[list[str | Exception]]) -> None:
        self.script, self.calls = script, 0

    async def generate(self, system: str, user: str) -> str:
        return ""

    async def stream(self, system: str, user: str):  # type: ignore[no-untyped-def]
        steps = self.script[self.calls]
        self.calls += 1
        for step in steps:
            if isinstance(step, Exception):
                raise step
            yield step


async def collect(llm: ResilientLLM) -> list[str]:
    return [piece async for piece in llm.stream("s", "u")]


async def test_stream_retries_a_failure_before_the_first_piece() -> None:
    inner = StreamScripted([[RuntimeError("429")], ["hello ", "world"]])
    assert await collect(ResilientLLM(inner, max_attempts=2, hedge_after=None)) == ["hello ", "world"]
    assert inner.calls == 2


async def test_stream_does_not_retry_after_output_started() -> None:
    inner = StreamScripted([["partial ", RuntimeError("cut")], ["never used"]])
    with pytest.raises(RuntimeError):
        await collect(ResilientLLM(inner, max_attempts=2, hedge_after=None))
    assert inner.calls == 1



    