from collections.abc import Sequence

import pytest

from adapters.fake_embedder import HashEmbedder
from adapters.memory_doc_state import InMemoryDocStateStore
from adapters.memory_vector_store import InMemoryVectorStore
from adapters.simple_chunker import ParagraphChunker
from domain.models import (
    DocumentEvent,
    DocumentId,
    EmbeddedChunk,
    GroupId,
    Operation,
    PromotionOutcome,
    SearchHit,
    SecurityContext,
    TenantId,
    UserId,
)
from domain.ports import DocStateStore, VectorStore
from ingestion.worker import IngestionWorker

T = TenantId("t1")
D = DocumentId("d1")
CTX = SecurityContext(T, UserId("u1"), frozenset({GroupId("g1")}), 1)
QUERY = (0.5,) * 8


class CrashAfterUpsert:
    """Wraps a VectorStore and simulates a worker dying right after the index write."""

    def __init__(self, inner: VectorStore) -> None:
        self._inner = inner
        self.crash_next = False

    @property
    def index_version(self) -> str:
        return self._inner.index_version

    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        await self._inner.upsert(chunks)
        if self.crash_next:
            self.crash_next = False
            raise RuntimeError("simulated crash")

    async def search(
        self, ctx: SecurityContext, query_vector: Sequence[float], top_k: int
    ) -> list[SearchHit]:
        return await self._inner.search(ctx, query_vector, top_k)

    async def delete_document_versions(
        self, tenant_id: TenantId, document_id: DocumentId, *, below_version: int
    ) -> int:
        return await self._inner.delete_document_versions(
            tenant_id, document_id, below_version=below_version
        )


def build() -> tuple[IngestionWorker, DocStateStore, VectorStore, CrashAfterUpsert]:
    state = InMemoryDocStateStore()
    inner = InMemoryVectorStore()
    crashing = CrashAfterUpsert(inner)
    worker = IngestionWorker(state, crashing, ParagraphChunker(max_chars=10), HashEmbedder())
    return worker, state, inner, crashing


def upsert(version: int, text: str) -> DocumentEvent:
    return DocumentEvent(Operation.UPSERT, T, D, version, title="doc", text=text)


async def versions_in_index(vectors: VectorStore) -> list[int]:
    return sorted(h.version for h in await vectors.search(CTX, QUERY, top_k=50))


async def test_happy_path_promotes_and_indexes() -> None:
    worker, state, vectors, _ = build()
    assert await worker.handle(upsert(1, "aaa one\n\nbbb two")) is PromotionOutcome.PROMOTED
    s = await state.get(T, D)
    assert s is not None and s.active_version == 1 and s.is_searchable
    assert await versions_in_index(vectors) == [1, 1]  # two chunks


async def test_duplicate_event_is_a_noop() -> None:
    worker, _, vectors, _ = build()
    await worker.handle(upsert(1, "aaa one\n\nbbb two"))
    assert await worker.handle(upsert(1, "aaa one\n\nbbb two")) is PromotionOutcome.ALREADY_ACTIVE
    assert await versions_in_index(vectors) == [1, 1]  # no duplicate chunks


async def test_out_of_order_old_version_never_written() -> None:
    worker, state, vectors, _ = build()
    await worker.handle(upsert(2, "ccc three\n\nddd four"))
    assert await worker.handle(upsert(1, "aaa one\n\nbbb two")) is PromotionOutcome.STALE
    s = await state.get(T, D)
    assert s is not None and s.active_version == 2
    assert await versions_in_index(vectors) == [2, 2]


async def test_update_replaces_old_chunks_after_promotion() -> None:
    worker, _, vectors, _ = build()
    await worker.handle(upsert(1, "aaa one\n\nbbb two"))
    await worker.handle(upsert(2, "ccc three\n\nddd four"))
    assert await versions_in_index(vectors) == [2, 2]


async def test_crash_after_upsert_keeps_old_version_then_retry_heals() -> None:
    worker, state, vectors, crashing = build()
    await worker.handle(upsert(1, "aaa one\n\nbbb two"))

    crashing.crash_next = True
    with pytest.raises(RuntimeError):
        await worker.handle(upsert(2, "ccc three\n\nddd four"))

    s = await state.get(T, D)
    assert s is not None
    assert s.active_version == 1  # never promoted, so users still see v1
    assert s.latest_seen_version == 2  # but we know v2 is in progress
    assert await versions_in_index(vectors) == [1, 1, 2, 2]  # v2 chunks are orphans

    await worker.handle(upsert(2, "ccc three\n\nddd four"))  # redelivery
    s = await state.get(T, D)
    assert s is not None and s.active_version == 2
    assert await versions_in_index(vectors) == [2, 2]  # no duplicates, v1 cleaned up


async def test_late_update_after_delete_is_stale() -> None:
    worker, state, _, _ = build()
    await worker.handle(upsert(10, "aaa one"))
    await worker.handle(DocumentEvent(Operation.DELETE, T, D, 12))
    assert await worker.handle(upsert(11, "bbb two")) is PromotionOutcome.STALE
    s = await state.get(T, D)
    assert s is not None and not s.is_searchable



    