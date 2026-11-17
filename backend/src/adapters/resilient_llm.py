from __future__ import annotations

import asyncio
import logging

from domain.ports import LLM

log = logging.getLogger("rag.llm")


class ResilientLLM:
    """Wraps any LLM: retries failures and hedges slow calls.

    Up to `max_attempts` requests are made in total. If the first is still running after
    `hedge_after` seconds, a backup starts without cancelling it, and the first success wins.
    Cost: extra calls for the slow tail only.
    """

    def __init__(
        self, inner: LLM, *, max_attempts: int = 2, hedge_after: float | None = 1.5
    ) -> None:
        self._inner = inner
        self._max_attempts = max_attempts
        self._hedge_after = hedge_after

    async def generate(self, system: str, user: str) -> str:
        attempts = 1
        pending: set[asyncio.Future[str]] = {
            asyncio.ensure_future(self._inner.generate(system, user))
        }
        last: BaseException | None = None
        try:
            while pending:
                can_hedge = attempts == 1 and self._max_attempts > 1
                done, pending = await asyncio.wait(
                    pending,
                    timeout=self._hedge_after if can_hedge else None,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:  # still running after hedge_after: start a backup
                    attempts += 1
                    log.info("hedging slow LLM call (attempt %d)", attempts)
                    pending.add(asyncio.ensure_future(self._inner.generate(system, user)))
                    continue
                for task in done:
                    exc = task.exception()
                    if exc is None:
                        return task.result()
                    last = exc
                    log.warning("LLM attempt failed: %r", exc)
                    if attempts < self._max_attempts:
                        attempts += 1
                        pending.add(asyncio.ensure_future(self._inner.generate(system, user)))
            raise last if last is not None else RuntimeError("no LLM attempt completed")
        finally:
            for task in pending:
                task.cancel()


                