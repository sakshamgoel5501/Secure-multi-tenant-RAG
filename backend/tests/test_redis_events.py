"""the codec test always runs; the rest need RAG_REDIS_URL"""

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from adapters.fake_embedder import HashEmbedder
from adapters.memory_doc_state import InMemoryDocStateStore
from adapters.memory_vector_store import InMemoryVectorStore
from adapters.redis_bus import RedisEventBus, decode_event, encode_event
from adapters.simple_chunker import ParagraphChunker
from domain.models import (
    DocumentEvent,
    DocumentId,
    GroupId,
    Operation,
    SecurityContext,
    TenantId,
    UserId,
)
from ingestion.consumer import IngestionConsumer
from ingestion.worker import IngestionWorker

URL = os.environ.get("RAG_REDIS_URL")
needs_redis = pytest.mark.skipif(URL is None, reason="set RAG_REDIS_URL=redis://localhost:6379/0")

T = TenantId("t1")
D = DocumentId("d1")


def event(version: int = 1, text: str = "hello") -> DocumentEvent:
    return DocumentEvent(Operation.UPSERT, T, D, version, "doc", text)


class Recorder:
    """Handler stub: fails the first `fail_times` calls, then records events."""

    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls = 0
        self.events: list[DocumentEvent] = []

    async def handle(self, event: DocumentEvent) -> None:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("boom")
        self.events.append(event)


@pytest_asyncio.fixture
async def bus() -> AsyncIterator[RedisEventBus]:
    assert URL is not None
    r = Redis.from_url(URL, decode_responses=True)
    suffix = uuid4().hex[:8]
    b = RedisEventBus(r, stream=f"test:events:{suffix}", dlq=f"test:dlq:{suffix}")
    await b.ensure()
    yield b
    await b.destroy()
    await r.aclose()


def test_codec_round_trip() -> None:
    e = DocumentEvent(Operation.DELETE, T, D, 7, "t", "line1\nline2 \u00e9")
    assert decode_event(encode_event(e)) == e


@needs_redis
async def test_published_event_is_handled_and_acked(bus: RedisEventBus) -> None:
    handler = Recorder()
    consumer = IngestionConsumer(bus, handler)
    await bus.publish(event())
    assert await consumer.run_once() == 1
    assert handler.events == [event()]
    assert await bus.pending_count() == 0


@needs_redis
async def test_transient_failure_is_retried(bus: RedisEventBus) -> None:
    handler = Recorder(fail_times=1)
    consumer = IngestionConsumer(bus, handler, max_deliveries=3, claim_idle_ms=0)
    await bus.publish(event())
    assert await consumer.run_once() == 0  # failed, left pending
    assert await bus.pending_count() == 1
    assert await consumer.run_once() == 1  # re-claimed and succeeded
    assert len(handler.events) == 1
    assert await bus.pending_count() == 0
    assert await bus.dlq_entries() == []


@needs_redis
async def test_poison_event_is_dead_lettered_after_max_deliveries(bus: RedisEventBus) -> None:
    handler = Recorder(fail_times=99)
    consumer = IngestionConsumer(bus, handler, max_deliveries=3, claim_idle_ms=0)
    await bus.publish(event())
    assert [await consumer.run_once() for _ in range(3)] == [0, 0, 1]
    assert await consumer.run_once() == 0  # nothing left to retry
    assert handler.calls == 3
    assert await bus.pending_count() == 0
    [entry] = await bus.dlq_entries()
    assert "boom" in entry["error"]
    assert entry["deliveries"] == "3"


@needs_redis
async def test_undecodable_message_goes_straight_to_dlq(bus: RedisEventBus) -> None:
    handler = Recorder()
    consumer = IngestionConsumer(bus, handler)
    await bus.publish_raw("not json")
    assert await consumer.run_once() == 1
    assert handler.calls == 0
    assert len(await bus.dlq_entries()) == 1
    assert await bus.pending_count() == 0


@needs_redis
async def test_out_of_order_and_duplicate_events_converge(bus: RedisEventBus) -> None:
    state = InMemoryDocStateStore()
    vectors = InMemoryVectorStore()
    worker = IngestionWorker(state, vectors, ParagraphChunker(max_chars=50), HashEmbedder())
    consumer = IngestionConsumer(bus, worker, claim_idle_ms=0)
    for version, text in [(2, "new text"), (1, "old text"), (2, "new text")]:
        await bus.publish(event(version, text))
    assert await consumer.run_once() == 3
    s = await state.get(T, D)
    assert s is not None and s.active_version == 2
    ctx = SecurityContext(T, UserId("u"), frozenset({GroupId("g")}), 1)
    hits = await vectors.search(ctx, (0.5,) * 8, top_k=10)
    assert [h.version for h in hits] == [2]


    