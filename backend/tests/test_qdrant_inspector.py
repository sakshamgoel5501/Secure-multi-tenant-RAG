"""
in-process Qdrant, no server). It also contains the regression test for the tenant-collision bug
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from qdrant_client import AsyncQdrantClient

from adapters.qdrant_inspector import QdrantIndexInspector
from adapters.qdrant_stores import QdrantVectorStore
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

T1 = TenantId("t1")
T2 = TenantId("t2")
A = DocumentId("a")
B = DocumentId("b")


def item(tenant: TenantId, doc: DocumentId, version: int, vec: tuple[float, ...]) -> EmbeddedChunk:
    text = f"{tenant} {doc} v{version}"
    chunk = Chunk(
        chunk_id=make_chunk_id(doc, version, 0),
        tenant_id=tenant,
        document_id=doc,
        version=version,
        ordinal=0,
        text=text,
        title=doc,
        section=None,
        start_offset=0,
        end_offset=len(text),
    )
    return EmbeddedChunk(chunk, vec)


def ctx(tenant: TenantId) -> SecurityContext:
    return SecurityContext(tenant, UserId("u"), frozenset({GroupId("g")}), 1)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncQdrantClient]:
    c = AsyncQdrantClient(":memory:")
    yield c
    await c.close()


async def test_inspector_lists_and_deletes_versions_per_tenant(
    client: AsyncQdrantClient,
) -> None:
    store = QdrantVectorStore(client, "test-v1", dim=2)
    await store.ensure()
    await store.upsert(
        [
            item(T1, A, 1, (1.0, 0.0)),
            item(T1, A, 2, (1.0, 0.0)),
            item(T1, B, 1, (0.0, 1.0)),
            item(T2, A, 1, (1.0, 0.0)),
        ]
    )
    inspector = QdrantIndexInspector(client, "rag_dense_test-v1")
    assert await inspector.list_versions(T1) == {A: {1, 2}, B: {1}}
    assert await inspector.delete_versions(T1, A, {1}) == 1
    assert await inspector.list_versions(T1) == {A: {2}, B: {1}}
    assert await inspector.list_versions(T2) == {A: {1}}  # other tenant untouched
    assert await inspector.delete_versions(T1, A, set()) == 0


async def test_same_document_id_in_two_tenants_does_not_collide(
    client: AsyncQdrantClient,
) -> None:
    store = QdrantVectorStore(client, "test-v1", dim=2)
    await store.ensure()
    await store.upsert([item(T1, A, 1, (1.0, 0.0)), item(T2, A, 1, (1.0, 0.0))])
    for tenant in (T1, T2):
        hits = await store.search(ctx(tenant), (1.0, 0.0), top_k=10)
        assert [h.tenant_id for h in hits] == [tenant]


        
