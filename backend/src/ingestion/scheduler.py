from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger("rag.scheduler")


async def run_periodically(
    job: Callable[[], Awaitable[None]], interval: float, stop: asyncio.Event
) -> None:
    """Runs `job` every `interval` seconds until `stop` is set. A failing run never ends the loop."""
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        try:
            await job()
        except Exception:
            log.exception("scheduled job failed")


            