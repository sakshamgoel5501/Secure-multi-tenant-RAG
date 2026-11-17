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


    