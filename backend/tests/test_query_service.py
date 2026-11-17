from collections.abc import Collection, Sequence

from adapters.fake_embedder import HashEmbedder
from adapters.memory_doc_state import InMemoryDocStateStore
from adapters.memory_vector_store import InMemoryVectorStore
from adapters.simple_chunker import ParagraphChunker
from domain.models import (
    AclSnapshot,
    ChunkId,
    DocumentEvent,
    DocumentId,
    EmbeddedChunk,
    GroupId,
    Operation,
    RetrievalSource,
    SearchHit,
    SecurityContext,
    TenantId,
    UserId,
)
from domain.ports import DocStateStore, Embedder, VectorStore
from ingestion.worker import IngestionWorker
from serving.query_service import QueryService

T = TenantId("t1")
D = DocumentId("d1")


class AllowAllAcl:
    """Test helper: grants group g1 on every document, so older tests stay focused."""

    async def acls_for(
        self,
        tenant_id: TenantId,
        document_ids: Collection[DocumentId],
        *,
        min_epoch: int,
    ) -> AclSnapshot:
        return AclSnapshot(min_epoch, {d: frozenset({GroupId("g1")}) for d in document_ids})
    


def ctx(tenant: TenantId = T) -> SecurityContext:
    return SecurityContext(tenant, UserId("u1"), frozenset({GroupId("g1")}), 1)


def build() -> tuple[IngestionWorker, QueryService, DocStateStore, VectorStore, Embedder]:
    state = InMemoryDocStateStore()
    vectors = InMemoryVectorStore()
    embedder = HashEmbedder()
    worker = IngestionWorker(state, vectors, ParagraphChunker(max_chars=10), embedder)
    return worker, QueryService(state, vectors, embedder, AllowAllAcl()), state, vectors, embedder


def upsert(tenant: TenantId, doc: str, version: int, text: str) -> DocumentEvent:
    return DocumentEvent(Operation.UPSERT, tenant, DocumentId(doc), version, "doc", text)


async def add_orphan(
    state: DocStateStore, vectors: VectorStore, embedder: Embedder, version: int, text: str
) -> None:
    """Simulates chunks written by a worker that crashed before promote()."""
    await state.record_seen(T, D, version)
    chunks = ParagraphChunker(max_chars=10).chunk(T, D, version, "doc", text)
    vecs = await embedder.embed([c.text for c in chunks])
    await vectors.upsert([EmbeddedChunk(c, v) for c, v in zip(chunks, vecs, strict=True)])


async def test_orphan_chunks_are_invisible() -> None:
    worker, service, state, vectors, embedder = build()
    await worker.handle(upsert(T, "d1", 1, "aaa one\n\nbbb two"))
    await add_orphan(state, vectors, embedder, 2, "ccc three\n\nddd four")

    raw = await vectors.search(ctx(), (0.5,) * 8, top_k=50)
    assert sorted(h.version for h in raw) == [1, 1, 2, 2]  # the index does hold the orphans

    hits = await service.retrieve(ctx(), "anything", top_k=10)
    assert [h.version for h in hits] == [1, 1]  # but the service never serves them


async def test_deleted_document_is_invisible_before_physical_cleanup() -> None:
    worker, service, _, vectors, _ = build()
    await worker.handle(upsert(T, "d1", 1, "aaa one\n\nbbb two"))
    await worker.handle(DocumentEvent(Operation.DELETE, T, D, 2))

    assert len(await vectors.search(ctx(), (0.5,) * 8, top_k=50)) == 2  # vectors still exist
    assert await service.retrieve(ctx(), "anything", top_k=10) == []


async def test_other_tenants_documents_are_never_returned() -> None:
    worker, service, _, _, _ = build()
    await worker.handle(upsert(T, "d1", 1, "aaa one"))
    await worker.handle(upsert(TenantId("t2"), "secret", 1, "top secret"))

    hits = await service.retrieve(ctx(), "anything", top_k=10)
    assert {h.tenant_id for h in hits} == {"t1"}


class LeakyVectorStore:
    """A buggy adapter that ignores the tenant filter and returns another tenant's hit."""

    @property
    def index_version(self) -> str:
        return "leaky"

    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        return None

    async def search(
        self, ctx: SecurityContext, query_vector: Sequence[float], top_k: int
    ) -> list[SearchHit]:
        return [
            SearchHit(
                chunk_id=ChunkId("x:1:0"),
                tenant_id=TenantId("t2"),
                document_id=DocumentId("x"),
                version=1,
                title="leak",
                section=None,
                start_offset=0,
                end_offset=1,
                text="leaked",
                score=1.0,
                source=RetrievalSource.DENSE,
            )
        ]

    async def delete_document_versions(
        self, tenant_id: TenantId, document_id: DocumentId, *, below_version: int
    ) -> int:
        return 0


async def test_service_drops_cross_tenant_hits_from_a_buggy_store() -> None:
    state = InMemoryDocStateStore()
    await state.promote(TenantId("t2"), DocumentId("x"), 1)  # even if it looks active elsewhere
    service = QueryService(state, LeakyVectorStore(), HashEmbedder(), AllowAllAcl())
    assert await service.retrieve(ctx(), "anything", top_k=10) == []


async def test_top_k_is_respected() -> None:
    worker, service, _, _, _ = build()
    for name in ("a", "b", "c"):
        await worker.handle(upsert(T, name, 1, f"{name} text"))
    assert len(await service.retrieve(ctx(), "anything", top_k=2)) == 2



    