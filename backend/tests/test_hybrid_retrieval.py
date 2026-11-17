import asyncio
from collections.abc import Collection, Sequence

import pytest

from adapters.fake_embedder import HashEmbedder
from adapters.memory_acl import InMemoryAclPrimary, InMemoryAclReplica
from adapters.memory_doc_state import InMemoryDocStateStore
from adapters.memory_lexical import InMemoryLexicalStore
from adapters.memory_vector_store import InMemoryVectorStore
from adapters.overlap_reranker import OverlapReranker
from adapters.simple_chunker import ParagraphChunker
from domain.errors import RetrievalUnavailable
from domain.models import (
    AclSnapshot,
    DocumentEvent,
    DocumentId,
    EmbeddedChunk,
    GroupId,
    Operation,
    SearchHit,
    SecurityContext,
    TenantId,
    UserId,
)
from ingestion.worker import IngestionWorker
from serving.query_service import QueryService

T = TenantId("t1")
G1 = GroupId("g1")
DOCS = {
    "a": "the quarterly report covers revenue",
    "b": "ticket ENG-4821 was escalated to security",
    "c": "the cafeteria menu changes weekly",
}


def ctx(epoch: int = 1) -> SecurityContext:
    return SecurityContext(T, UserId("u1"), frozenset({G1}), epoch)


class AllowAllAcl:
    async def acls_for(
        self, tenant_id: TenantId, document_ids: Collection[DocumentId], *, min_epoch: int
    ) -> AclSnapshot:
        return AclSnapshot(min_epoch, {d: frozenset({G1}) for d in document_ids})


class BrokenVectors:
    def __init__(self, fail: bool = False, delay: float = 0.0) -> None:
        self._fail = fail
        self._delay = delay

    @property
    def index_version(self) -> str:
        return "broken"

    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        return None

    async def search(
        self, ctx: SecurityContext, query_vector: Sequence[float], top_k: int
    ) -> list[SearchHit]:
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._fail:
            raise RuntimeError("vector backend down")
        return []

    async def delete_document_versions(
        self, tenant_id: TenantId, document_id: DocumentId, *, below_version: int
    ) -> int:
        return 0


class BrokenLexical:
    async def upsert(self, chunks: Sequence[object]) -> None:
        return None

    async def search(self, ctx: SecurityContext, query: str, top_k: int) -> list[SearchHit]:
        raise RuntimeError("lexical backend down")

    async def delete_document_versions(
        self, tenant_id: TenantId, document_id: DocumentId, *, below_version: int
    ) -> int:
        return 0


class SlowReranker:
    async def rerank(self, query: str, hits: Sequence[SearchHit], top_k: int) -> list[SearchHit]:
        await asyncio.sleep(1)
        return list(hits)


class RecordingReranker:
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def rerank(self, query: str, hits: Sequence[SearchHit], top_k: int) -> list[SearchHit]:
        self.seen.extend(h.document_id for h in hits)
        return list(hits)[:top_k]


async def seeded() -> tuple[
    InMemoryDocStateStore,
    InMemoryVectorStore,
    InMemoryLexicalStore,
    HashEmbedder,
    IngestionWorker,
]:
    state = InMemoryDocStateStore()
    vectors = InMemoryVectorStore()
    lexical = InMemoryLexicalStore()
    embedder = HashEmbedder()
    worker = IngestionWorker(state, vectors, ParagraphChunker(max_chars=200), embedder, lexical)
    for name, text in DOCS.items():
        await worker.handle(DocumentEvent(Operation.UPSERT, T, DocumentId(name), 1, name, text))
    return state, vectors, lexical, embedder, worker


async def test_lexical_match_surfaces_through_hybrid() -> None:
    state, vectors, lexical, embedder, _ = await seeded()
    svc = QueryService(state, vectors, embedder, AllowAllAcl(), lexical=lexical)
    hits = await svc.retrieve(ctx(), "ENG-4821", top_k=1)
    assert [h.document_id for h in hits] == ["b"]


async def test_worker_writes_to_both_stores() -> None:
    _, _, lexical, _, _ = await seeded()
    assert len(await lexical.search(ctx(), "ENG-4821", 5)) == 1


async def test_update_cleans_old_versions_in_lexical_store() -> None:
    _, _, lexical, _, worker = await seeded()
    await worker.handle(
        DocumentEvent(Operation.UPSERT, T, DocumentId("b"), 2, "b", "ticket ENG-4821 closed")
    )
    hits = await lexical.search(ctx(), "eng", 5)
    assert [h.version for h in hits] == [2]


async def test_dense_down_degrades_to_lexical_only() -> None:
    state, _, lexical, embedder, _ = await seeded()
    svc = QueryService(state, BrokenVectors(fail=True), embedder, AllowAllAcl(), lexical=lexical)
    # the broken store holds no data, so use the real lexical results
    result = await svc.retrieve_ex(ctx(), "ENG-4821", top_k=3)
    assert result.degraded == ("dense",)
    assert [h.document_id for h in result.hits] == ["b"]


async def test_lexical_down_degrades_to_dense_only() -> None:
    state, vectors, _, embedder, _ = await seeded()
    svc = QueryService(state, vectors, embedder, AllowAllAcl(), lexical=BrokenLexical())
    result = await svc.retrieve_ex(ctx(), "anything", top_k=3)
    assert result.degraded == ("lexical",)
    assert len(result.hits) == 3


async def test_all_retrievers_down_raises() -> None:
    state, _, _, embedder, _ = await seeded()
    svc = QueryService(
        state, BrokenVectors(fail=True), embedder, AllowAllAcl(), lexical=BrokenLexical()
    )
    with pytest.raises(RetrievalUnavailable):
        await svc.retrieve(ctx(), "q", top_k=3)


async def test_slow_dense_times_out_and_is_skipped() -> None:
    state, _, lexical, embedder, _ = await seeded()
    svc = QueryService(
        state,
        BrokenVectors(delay=1.0),
        embedder,
        AllowAllAcl(),
        lexical=lexical,
        retrieval_timeout=0.05,
    )
    result = await svc.retrieve_ex(ctx(), "ENG-4821", top_k=3)
    assert "dense" in result.degraded
    assert [h.document_id for h in result.hits] == ["b"]


async def test_reranker_reorders_results() -> None:
    state, vectors, _, embedder, _ = await seeded()
    svc = QueryService(state, vectors, embedder, AllowAllAcl(), reranker=OverlapReranker())
    hits = await svc.retrieve(ctx(), "cafeteria menu", top_k=3)
    assert hits[0].document_id == "c"
    assert hits[0].score == 1.0


async def test_slow_reranker_falls_back_to_fused_order() -> None:
    state, vectors, _, embedder, _ = await seeded()
    svc = QueryService(
        state, vectors, embedder, AllowAllAcl(), reranker=SlowReranker(), rerank_timeout=0.05
    )
    result = await svc.retrieve_ex(ctx(), "q", top_k=3)
    assert "reranker" in result.degraded
    assert len(result.hits) == 3


async def test_reranker_only_sees_authorized_documents() -> None:
    state, vectors, _, embedder, _ = await seeded()
    primary = InMemoryAclPrimary()
    replica = InMemoryAclReplica(primary)
    primary.set_acl(T, DocumentId("a"), {G1})
    epoch = primary.set_acl(T, DocumentId("c"), {G1})  # document b is not granted
    replica.sync()
    reranker = RecordingReranker()
    svc = QueryService(state, vectors, embedder, replica, reranker=reranker)
    await svc.retrieve(ctx(epoch), "q", top_k=5)
    assert sorted(reranker.seen) == ["a", "c"]


    