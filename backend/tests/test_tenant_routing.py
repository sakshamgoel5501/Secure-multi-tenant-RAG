import asyncio

from adapters.fake_embedder import HashEmbedder
from adapters.memory_lexical import InMemoryLexicalStore
from adapters.memory_vector_store import InMemoryVectorStore
from adapters.qdrant_stores import _slug
from adapters.tenant_layout import TenantLayout
from adapters.tenant_routing import RoutedLexicalStore, RoutedVectorStore
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


class MemVectors(InMemoryVectorStore):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.ensured = 0

    async def ensure(self) -> None:
        self.ensured += 1


class MemLexical(InMemoryLexicalStore):
    def __init__(self) -> None:
        super().__init__()
        self.ensured = 0

    async def ensure(self) -> None:
        self.ensured += 1


def chunk(tenant: str, doc: str = "d1", text: str = "alpha") -> Chunk:
    d = DocumentId(doc)
    return Chunk(make_chunk_id(d, 1, 0), TenantId(tenant), d, 1, 0, text, "t", None, 0, len(text))


def ctx(tenant: str) -> SecurityContext:
    return SecurityContext(TenantId(tenant), UserId("u"), frozenset({GroupId("g")}), 1)


def vectors() -> tuple[RoutedVectorStore, MemVectors, dict[str, MemVectors]]:
    shared, made = MemVectors("shared"), {}

    def make(t: TenantId) -> MemVectors:
        made[str(t)] = MemVectors(f"silo-{t}")
        return made[str(t)]

    return RoutedVectorStore(shared, {"t2"}, make), shared, made


async def test_each_tenant_lands_in_its_own_place_and_searches_only_there() -> None:
    routed, shared, made = vectors()
    vec = (await HashEmbedder().embed(["x"]))[0]
    await routed.upsert([EmbeddedChunk(chunk("t1"), vec), EmbeddedChunk(chunk("t2"), vec)])
    assert [h.tenant_id for h in await shared.search(ctx("t1"), vec, 10)] == ["t1"]
    assert await shared.search(ctx("t2"), vec, 10) == []  # the silo tenant never touched the pool
    assert [h.tenant_id for h in await made["t2"].search(ctx("t2"), vec, 10)] == ["t2"]
    assert [h.tenant_id for h in await routed.search(ctx("t2"), vec, 10)] == ["t2"]
    assert [h.tenant_id for h in await routed.search(ctx("t1"), vec, 10)] == ["t1"]


async def test_a_silo_is_created_and_ensured_once_even_under_concurrency() -> None:
    routed, _, made = vectors()
    vec = (await HashEmbedder().embed(["x"]))[0]
    await asyncio.gather(*(routed.upsert([EmbeddedChunk(chunk("t2", f"d{i}"), vec)]) for i in range(5)))
    assert made["t2"].ensured == 1 and len(made) == 1


async def test_startup_ensure_creates_the_pool_and_every_configured_silo() -> None:
    routed, shared, made = vectors()
    await routed.ensure()
    assert shared.ensured == 1 and made["t2"].ensured == 1


async def test_delete_follows_the_tenant() -> None:
    routed, _, made = vectors()
    vec = (await HashEmbedder().embed(["x"]))[0]
    d = DocumentId("d1")
    first, second = chunk("t2"), chunk("t2")
    await routed.upsert([EmbeddedChunk(first, vec)])
    second = Chunk(make_chunk_id(d, 2, 0), TenantId("t2"), d, 2, 0, "b", "t", None, 0, 1)
    await routed.upsert([EmbeddedChunk(second, vec)])
    assert await routed.delete_document_versions(TenantId("t2"), d, below_version=2) == 1
    assert [h.version for h in await made["t2"].search(ctx("t2"), vec, 10)] == [2]


async def test_lexical_routing_gives_a_silo_its_own_statistics() -> None:
    shared, made = MemLexical(), {}

    def make(t: TenantId) -> MemLexical:
        made[str(t)] = MemLexical()
        return made[str(t)]

    routed = RoutedLexicalStore(shared, {"t2"}, make)
    await routed.upsert([chunk("t1", "a", "alpha beta"), chunk("t2", "b", "alpha gamma")])
    assert [h.document_id for h in await routed.search(ctx("t1"), "alpha", 5)] == ["a"]
    assert [h.document_id for h in await routed.search(ctx("t2"), "alpha", 5)] == ["b"]
    assert await shared.search(ctx("t2"), "alpha", 5) == []


def test_layout_names() -> None:
    pool = TenantLayout("v1", ())
    assert (pool.dense_collection("t1"), pool.lexical_collection("t1")) == ("rag_dense_v1", "rag_lexical")
    silo = TenantLayout("v1", {"tenant-2", "tenant_2"})
    assert silo.prefix("tenant-1") == "rag"  # not a silo tenant
    assert silo.prefix("tenant-2") != silo.prefix("tenant_2")  # same slug, different collections
    assert _slug("tenant-2") in silo.prefix("tenant-2")
    assert silo.dense_collection("tenant-2").endswith("_dense_v1")


    