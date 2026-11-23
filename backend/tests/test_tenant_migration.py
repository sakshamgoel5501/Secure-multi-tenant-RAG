from collections.abc import AsyncIterator

import pytest_asyncio
from qdrant_client import AsyncQdrantClient

from adapters.qdrant_stores import QdrantVectorStore
from adapters.routed_inspector import RoutedInspector
from adapters.tenant_layout import TenantLayout
from adapters.tenant_migration import move_tenant_points
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

POOL = TenantLayout("test-v1", ())
SILO = TenantLayout("test-v1", {"t2"})


def item(tenant: str, doc: str) -> EmbeddedChunk:
    d = DocumentId(doc)
    c = Chunk(make_chunk_id(d, 1, 0), TenantId(tenant), d, 1, 0, "text", "t", None, 0, 4)
    return EmbeddedChunk(c, (1.0, 0.0))


def ctx(tenant: str) -> SecurityContext:
    return SecurityContext(TenantId(tenant), UserId("u"), frozenset({GroupId("g")}), 1)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncQdrantClient]:
    c = AsyncQdrantClient(":memory:")
    yield c
    await c.close()


async def test_moving_a_tenant_copies_verifies_then_removes_from_the_source(client: AsyncQdrantClient) -> None:
    pool = QdrantVectorStore(client, "test-v1", 2, prefix=POOL.prefix("t2"))
    silo = QdrantVectorStore(client, "test-v1", 2, prefix=SILO.prefix("t2"))
    await pool.ensure()
    await silo.ensure()
    await pool.upsert([item("t1", "a"), item("t2", "b"), item("t2", "c")])

    copied, held = await move_tenant_points(
        client, POOL.dense_collection("t2"), SILO.dense_collection("t2"), "t2"
    )
    assert (copied, held) == (2, 2)
    assert await pool.search(ctx("t2"), (1.0, 0.0), 10) == []
    assert {h.document_id for h in await silo.search(ctx("t2"), (1.0, 0.0), 10)} == {"b", "c"}
    assert [h.document_id for h in await pool.search(ctx("t1"), (1.0, 0.0), 10)] == ["a"]  # untouched
    assert await move_tenant_points(client, POOL.dense_collection("t2"), SILO.dense_collection("t2"), "t2") == (0, 0)


async def test_a_missing_source_is_a_no_op(client: AsyncQdrantClient) -> None:
    assert await move_tenant_points(client, "does-not-exist", "also-missing", "t2") == (0, 0)


async def test_the_inspector_follows_each_tenant_and_reads_a_missing_collection_as_empty(
    client: AsyncQdrantClient,
) -> None:
    pool = QdrantVectorStore(client, "test-v1", 2)
    silo = QdrantVectorStore(client, "test-v1", 2, prefix=SILO.prefix("t2"))
    await pool.ensure()
    await silo.ensure()
    await pool.upsert([item("t1", "a")])
    await silo.upsert([item("t2", "b")])
    inspector = RoutedInspector(client, SILO.dense_collection)
    assert await inspector.list_versions(TenantId("t1")) == {DocumentId("a"): {1}}
    assert await inspector.list_versions(TenantId("t2")) == {DocumentId("b"): {1}}
    assert await RoutedInspector(client, TenantLayout("test-v1", {"t3"}).dense_collection).list_versions(
        TenantId("t3")
    ) == {}
    assert await inspector.document_versions(TenantId("t2"), DocumentId("b")) == {1: 1}
    assert await inspector.delete_versions(TenantId("t2"), DocumentId("b"), {1}) == 1


    