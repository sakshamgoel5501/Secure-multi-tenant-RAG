from adapters.memory_lexical import InMemoryLexicalStore
from adapters.memory_vector_store import InMemoryVectorStore
from domain.models import (
    Chunk,
    DocumentId,
    EmbeddedChunk,
    GroupId,
    SecurityContext,
    TenantId,
    UserId,
    make_chunk_id,
)


def chunk(tenant: str) -> Chunk:
    d = DocumentId("same-doc")  # identical document id, and therefore identical chunk id
    return Chunk(make_chunk_id(d, 1, 0), TenantId(tenant), d, 1, 0, "alpha", "t", None, 0, 5)


def ctx(tenant: str) -> SecurityContext:
    return SecurityContext(TenantId(tenant), UserId("u"), frozenset({GroupId("g")}), 1)


async def test_vector_store_keeps_both_tenants_rows() -> None:
    store = InMemoryVectorStore()
    await store.upsert([EmbeddedChunk(chunk("t1"), (1.0, 0.0)), EmbeddedChunk(chunk("t2"), (1.0, 0.0))])
    for tenant in ("t1", "t2"):
        hits = await store.search(ctx(tenant), (1.0, 0.0), top_k=10)
        assert [h.tenant_id for h in hits] == [tenant]


async def test_lexical_store_keeps_both_tenants_rows() -> None:
    store = InMemoryLexicalStore()
    await store.upsert([chunk("t1"), chunk("t2")])
    for tenant in ("t1", "t2"):
        hits = await store.search(ctx(tenant), "alpha", top_k=10)
        assert [h.tenant_id for h in hits] == [tenant]


        