from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from qdrant_client import AsyncQdrantClient

from adapters.qdrant_stores import QdrantLexicalStore, QdrantVectorStore
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
from domain.ports import LexicalStore, VectorStore


def ctx(tenant: str) -> SecurityContext:
    return SecurityContext(TenantId(tenant), UserId("u1"), frozenset({GroupId("g1")}), 1)


def chunk(tenant: str, doc: str, version: int, text: str) -> Chunk:
    d = DocumentId(doc)
    return Chunk(
        chunk_id=make_chunk_id(d, version, 0),
        tenant_id=TenantId(tenant),
        document_id=d,
        version=version,
        ordinal=0,
        text=text,
        title=doc,
        section=None,
        start_offset=0,
        end_offset=len(text),
    )


def item(tenant: str, doc: str, version: int, vec: tuple[float, ...]) -> EmbeddedChunk:
    return EmbeddedChunk(chunk(tenant, doc, version, f"{doc} v{version}"), vec)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncQdrantClient]:
    c = AsyncQdrantClient(":memory:")
    yield c
    await c.close()


@pytest_asyncio.fixture
async def dense(client: AsyncQdrantClient) -> VectorStore:
    store = QdrantVectorStore(client, "test-v1", dim=2)
    await store.ensure()
    return store


@pytest_asyncio.fixture
async def lexical(client: AsyncQdrantClient) -> LexicalStore:
    try:
        store = QdrantLexicalStore(client)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"BM25 model unavailable: {exc}")
    await store.ensure()
    return store


async def test_dense_ranks_by_similarity(dense: VectorStore) -> None:
    await dense.upsert([item("t1", "a", 1, (1.0, 0.0)), item("t1", "b", 1, (0.0, 1.0))])
    hits = await dense.search(ctx("t1"), (1.0, 0.1), top_k=2)
    assert [h.document_id for h in hits] == ["a", "b"]


async def test_dense_never_crosses_tenants(dense: VectorStore) -> None:
    await dense.upsert([item("t1", "a", 1, (1.0, 0.0)), item("t2", "secret", 1, (1.0, 0.0))])
    hits = await dense.search(ctx("t1"), (1.0, 0.0), top_k=10)
    assert {h.tenant_id for h in hits} == {"t1"}


async def test_dense_upsert_is_idempotent(dense: VectorStore) -> None:
    row = item("t1", "a", 1, (1.0, 0.0))
    await dense.upsert([row])
    await dense.upsert([row])
    assert len(await dense.search(ctx("t1"), (1.0, 0.0), top_k=10)) == 1


async def test_dense_may_return_stale_versions(dense: VectorStore) -> None:
    await dense.upsert([item("t1", "a", 1, (1.0, 0.0)), item("t1", "a", 2, (1.0, 0.0))])
    hits = await dense.search(ctx("t1"), (1.0, 0.0), top_k=10)
    assert sorted(h.version for h in hits) == [1, 2]


async def test_dense_delete_old_versions_only(dense: VectorStore) -> None:
    await dense.upsert([item("t1", "a", 1, (1.0, 0.0)), item("t1", "a", 2, (1.0, 0.0))])
    removed = await dense.delete_document_versions(TenantId("t1"), DocumentId("a"), below_version=2)
    assert removed == 1
    hits = await dense.search(ctx("t1"), (1.0, 0.0), top_k=10)
    assert [h.version for h in hits] == [2]


async def test_lexical_exact_term_match(lexical: LexicalStore) -> None:
    await lexical.upsert(
        [
            chunk("t1", "a", 1, "the quarterly report covers revenue"),
            chunk("t1", "b", 1, "ticket ENG-4821 was escalated to security"),
            chunk("t1", "c", 1, "the cafeteria menu changes weekly"),
        ]
    )
    hits = await lexical.search(ctx("t1"), "ENG-4821", top_k=3)
    assert [h.document_id for h in hits] == ["b"]


async def test_lexical_never_crosses_tenants(lexical: LexicalStore) -> None:
    await lexical.upsert([chunk("t1", "a", 1, "alpha"), chunk("t2", "secret", 1, "alpha alpha")])
    hits = await lexical.search(ctx("t1"), "alpha", top_k=10)
    assert {h.tenant_id for h in hits} == {"t1"}


async def test_lexical_idempotent_and_stale_versions(lexical: LexicalStore) -> None:
    c1 = chunk("t1", "a", 1, "alpha")
    await lexical.upsert([c1])
    await lexical.upsert([c1])
    await lexical.upsert([chunk("t1", "a", 2, "alpha")])
    hits = await lexical.search(ctx("t1"), "alpha", top_k=10)
    assert sorted(h.version for h in hits) == [1, 2]


async def test_lexical_delete_old_versions_only(lexical: LexicalStore) -> None:
    await lexical.upsert([chunk("t1", "a", 1, "alpha"), chunk("t1", "a", 2, "alpha")])
    removed = await lexical.delete_document_versions(
        TenantId("t1"), DocumentId("a"), below_version=2
    )
    assert removed == 1
    hits = await lexical.search(ctx("t1"), "alpha", top_k=10)
    assert [h.version for h in hits] == [2]


    