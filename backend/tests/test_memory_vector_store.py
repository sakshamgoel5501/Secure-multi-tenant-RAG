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
from domain.ports import VectorStore


def make_store() -> VectorStore:
    return InMemoryVectorStore()  # annotated as the Protocol so mypy checks the match


def ctx(tenant: str) -> SecurityContext:
    return SecurityContext(TenantId(tenant), UserId("u1"), frozenset({GroupId("g1")}), 1)


def item(tenant: str, doc: str, version: int, ordinal: int, vec: tuple[float, ...]) -> EmbeddedChunk:
    d = DocumentId(doc)
    chunk = Chunk(
        chunk_id=make_chunk_id(d, version, ordinal),
        tenant_id=TenantId(tenant),
        document_id=d,
        version=version,
        ordinal=ordinal,
        text=f"{doc} v{version} #{ordinal}",
        title=doc,
        section=None,
        start_offset=0,
        end_offset=10,
    )
    return EmbeddedChunk(chunk, vec)


async def test_search_ranks_by_similarity() -> None:
    store = make_store()
    await store.upsert([item("t1", "a", 1, 0, (1.0, 0.0)), item("t1", "b", 1, 0, (0.0, 1.0))])
    hits = await store.search(ctx("t1"), (1.0, 0.1), top_k=2)
    assert [h.document_id for h in hits] == ["a", "b"]


async def test_search_never_crosses_tenants() -> None:
    store = make_store()
    await store.upsert([item("t1", "a", 1, 0, (1.0, 0.0)), item("t2", "secret", 1, 0, (1.0, 0.0))])
    hits = await store.search(ctx("t1"), (1.0, 0.0), top_k=10)
    assert {h.tenant_id for h in hits} == {"t1"}


async def test_upsert_is_idempotent() -> None:
    store = make_store()
    row = item("t1", "a", 1, 0, (1.0, 0.0))
    await store.upsert([row])
    await store.upsert([row])  # simulated retry after a crash
    assert len(await store.search(ctx("t1"), (1.0, 0.0), top_k=10)) == 1


async def test_store_may_return_stale_versions() -> None:
    # Documents the contract: the store is NOT the authority on what is active.
    store = make_store()
    await store.upsert([item("t1", "a", 1, 0, (1.0, 0.0)), item("t1", "a", 2, 0, (1.0, 0.0))])
    hits = await store.search(ctx("t1"), (1.0, 0.0), top_k=10)
    assert {h.version for h in hits} == {1, 2}


async def test_delete_old_versions_only() -> None:
    store = make_store()
    await store.upsert([item("t1", "a", 1, 0, (1.0, 0.0)), item("t1", "a", 2, 0, (1.0, 0.0))])
    removed = await store.delete_document_versions(TenantId("t1"), DocumentId("a"), below_version=2)
    assert removed == 1
    hits = await store.search(ctx("t1"), (1.0, 0.0), top_k=10)
    assert [h.version for h in hits] == [2]


    