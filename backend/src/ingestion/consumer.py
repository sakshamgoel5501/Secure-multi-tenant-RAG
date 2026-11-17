from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from adapters.redis_bus import RedisEventBus, decode_event
from domain.models import DocumentEvent

log = logging.getLogger("rag.consumer")


class EventHandler(Protocol):
    async def handle(self, event: DocumentEvent) -> object: ...


class IngestionConsumer:
    """Pulls events from the bus and hands them to the worker.

    Ack only after success. A failure leaves the message pending; it is re-claimed after
    `claim_idle_ms` and retried. After `max_deliveries` attempts it goes to the DLQ so one poison
    message can't block the stream. The consumer does no ordering or dedup: the worker's
    compare-and-set makes duplicates and reordering safe.
    """

    def __init__(
        self,
        bus: RedisEventBus,
        handler: EventHandler,
        *,
        name: str = "worker-1",
        max_deliveries: int = 5,
        claim_idle_ms: int = 30_000,
        batch: int = 10,
    ) -> None:
        self._bus = bus
        self._handler = handler
        self._name = name
        self._max = max_deliveries
        self._claim_idle_ms = claim_idle_ms
        self._batch = batch

    async def run_once(self, *, block_ms: int | None = None) -> int:
        """One pass. Returns how many messages reached a final state (acked or dead-lettered)."""
        finished = 0
        stale = await self._bus.claim_stale(self._name, self._claim_idle_ms, self._batch)
        for msg_id, raw in stale:
            finished += await self._process(msg_id, raw)
        fresh = await self._bus.read_new(self._name, count=self._batch, block_ms=block_ms)
        for msg_id, raw in fresh:
            finished += await self._process(msg_id, raw)
        return finished

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.run_once(block_ms=1000)
            except Exception:
                log.exception("consumer loop error; backing off")
                await asyncio.sleep(1)

    async def _process(self, msg_id: str, raw: str) -> int:
        try:
            event = decode_event(raw)
        except Exception as exc:  # noqa: BLE001
            await self._bus.dead_letter(msg_id, raw, f"undecodable: {exc!r}", 0)
            return 1
        try:
            await self._handler.handle(event)
        except Exception as exc:  # noqa: BLE001
            attempts = await self._bus.deliveries(msg_id)
            log.warning("event %s failed (attempt %d/%d): %r", msg_id, attempts, self._max, exc)
            if attempts >= self._max:
                await self._bus.dead_letter(msg_id, raw, repr(exc), attempts)
                return 1
            return 0  # stays pending; re-claimed later
        await self._bus.ack(msg_id)
        return 1
    


    