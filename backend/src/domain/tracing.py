from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token


class Trace:
    def __init__(self) -> None:
        self.stages: dict[str, float] = {}  # stage name -> accumulated milliseconds

    def add(self, name: str, ms: float) -> None:
        self.stages[name] = self.stages.get(name, 0.0) + ms


_current: ContextVar[Trace | None] = ContextVar("rag_trace", default=None)


def start_trace() -> tuple[Trace, Token[Trace | None]]:
    trace = Trace()
    return trace, _current.set(trace)


def finish_trace(token: Token[Trace | None]) -> None:
    _current.reset(token)


@contextmanager
def span(name: str) -> Iterator[None]:
    """Time a block. A no-op when no trace is active, so domain code never depends on the API."""
    trace = _current.get()
    started = time.perf_counter()
    try:
        yield
    finally:
        if trace is not None:
            trace.add(name, (time.perf_counter() - started) * 1000)



            