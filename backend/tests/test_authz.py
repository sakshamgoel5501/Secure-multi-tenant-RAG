import pytest

from adapters.fake_embedder import HashEmbedder
from adapters.memory_acl import InMemoryAclPrimary, InMemoryAclReplica
from adapters.memory_doc_state import InMemoryDocStateStore
from adapters.memory_vector_store import InMemoryVectorStore
from adapters.simple_chunker import ParagraphChunker
from domain.errors import AuthzUnavailable
from domain.models import (
    DocumentEvent,
    DocumentId,
    GroupId,
    Operation,
    SecurityContext,
    TenantId,
    UserId,
)
from ingestion.worker import IngestionWorker
from serving.query_service import QueryService

T = TenantId("t1")
D = DocumentId("d1")
G1 = GroupId("g1")
G2 = GroupId("g2")


def ctx(group: GroupId, epoch: int) -> SecurityContext:
    return SecurityContext(T, UserId("u1"), frozenset({group}), epoch)


async def build() -> tuple[QueryService, InMemoryAclPrimary, InMemoryAclReplica]:
    state = InMemoryDocStateStore()
    vectors = InMemoryVectorStore()
    embedder = HashEmbedder()
    worker = IngestionWorker(state, vectors, ParagraphChunker(max_chars=50), embedder)
    await worker.handle(DocumentEvent(Operation.UPSERT, T, D, 1, "doc", "aaa one"))
    primary = InMemoryAclPrimary()
    replica = InMemoryAclReplica(primary)
    return QueryService(state, vectors, embedder, replica), primary, replica


async def test_group_in_acl_can_read() -> None:
    service, primary, replica = await build()
    epoch = primary.set_acl(T, D, {G1})
    replica.sync()
    assert len(await service.retrieve(ctx(G1, epoch), "q", top_k=5)) == 1


async def test_group_not_in_acl_is_denied() -> None:
    service, primary, replica = await build()
    epoch = primary.set_acl(T, D, {G1})
    replica.sync()
    assert await service.retrieve(ctx(G2, epoch), "q", top_k=5) == []


async def test_document_without_acl_is_denied() -> None:
    service, _, _ = await build()
    assert await service.retrieve(ctx(G1, 0), "q", top_k=5) == []


async def test_revocation_takes_effect_despite_stale_vector_metadata() -> None:
    service, primary, replica = await build()
    e1 = primary.set_acl(T, D, {G1})
    replica.sync()
    assert len(await service.retrieve(ctx(G1, e1), "q", top_k=5)) == 1

    e2 = primary.set_acl(T, D, {G2})  # group g1 removed from the document
    replica.sync()
    assert await service.retrieve(ctx(G1, e2), "q", top_k=5) == []


async def test_replica_behind_required_epoch_fails_closed() -> None:
    service, primary, replica = await build()
    e1 = primary.set_acl(T, D, {G1})
    replica.sync()
    e2 = primary.set_acl(T, D, {G2})  # revocation committed, replica not synced yet

    with pytest.raises(AuthzUnavailable):
        await service.retrieve(ctx(G1, e2), "q", top_k=5)
    # A request pinned before the revocation is still evaluated at its own epoch.
    assert len(await service.retrieve(ctx(G1, e1), "q", top_k=5)) == 1


async def test_replica_down_fails_closed() -> None:
    service, primary, replica = await build()
    epoch = primary.set_acl(T, D, {G1})
    replica.sync()
    replica.up = False
    with pytest.raises(AuthzUnavailable):
        await service.retrieve(ctx(G1, epoch), "q", top_k=5)


async def test_acls_are_tenant_scoped() -> None:
    service, primary, replica = await build()
    epoch = primary.set_acl(TenantId("t2"), D, {G1})  # same doc id, other tenant
    replica.sync()
    assert await service.retrieve(ctx(G1, epoch), "q", top_k=5) == []




    