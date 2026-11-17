import httpx

from adapters.fake_embedder import HashEmbedder
from adapters.memory_acl import InMemoryAclPrimary, InMemoryAclReplica
from adapters.memory_doc_state import InMemoryDocStateStore
from adapters.memory_vector_store import InMemoryVectorStore
from adapters.simple_chunker import ParagraphChunker
from domain.models import DocumentEvent, DocumentId, GroupId, Operation, TenantId
from ingestion.worker import IngestionWorker
from serving.api import create_app
from serving.query_service import QueryService

T = TenantId("t1")
D = DocumentId("d1")
G1 = GroupId("g1")
G2 = GroupId("g2")


async def build() -> tuple[httpx.AsyncClient, InMemoryAclPrimary, InMemoryAclReplica]:
    state = InMemoryDocStateStore()
    vectors = InMemoryVectorStore()
    embedder = HashEmbedder()
    worker = IngestionWorker(state, vectors, ParagraphChunker(max_chars=200), embedder)
    await worker.handle(DocumentEvent(Operation.UPSERT, T, D, 1, "doc", "aaa one"))
    primary = InMemoryAclPrimary()
    replica = InMemoryAclReplica(primary)
    app = create_app(QueryService(state, vectors, embedder, replica))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, primary, replica


def headers(
    epoch: int, group: str = "g1", tenant: str = "t1", user: str = "u1"
) -> dict[str, str]:
    return {
        "X-Tenant-Id": tenant,
        "X-User-Id": user,
        "X-Groups": group,
        "X-Policy-Epoch": str(epoch),
    }


async def test_authorized_user_gets_cited_hit() -> None:
    client, primary, replica = await build()
    epoch = primary.set_acl(T, D, {G1})
    replica.sync()
    r = await client.post("/search", json={"query": "q"}, headers=headers(epoch))
    assert r.status_code == 200
    [hit] = r.json()["hits"]
    assert hit["document_id"] == "d1"
    assert hit["version"] == 1
    assert hit["chunk_id"] == "d1:1:0"
    assert (hit["start_offset"], hit["end_offset"]) == (0, 7)


async def test_unauthorized_group_gets_empty_200_not_403() -> None:
    client, primary, replica = await build()
    epoch = primary.set_acl(T, D, {G1})
    replica.sync()
    r = await client.post("/search", json={"query": "q"}, headers=headers(epoch, group="g2"))
    assert r.status_code == 200
    assert r.json() == {"hits": []}


async def test_other_tenant_gets_nothing() -> None:
    client, primary, replica = await build()
    epoch = primary.set_acl(T, D, {G1})
    replica.sync()
    r = await client.post("/search", json={"query": "q"}, headers=headers(epoch, tenant="t2"))
    assert r.status_code == 200
    assert r.json() == {"hits": []}


async def test_lagging_replica_returns_503_without_leaking_state() -> None:
    client, primary, replica = await build()
    primary.set_acl(T, D, {G1})
    replica.sync()
    e2 = primary.set_acl(T, D, {G2})  # revocation committed, replica not synced
    r = await client.post("/search", json={"query": "q"}, headers=headers(e2))
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "1"
    assert "epoch" not in r.text


async def test_missing_identity_header_is_rejected() -> None:
    client, _, _ = await build()
    r = await client.post("/search", json={"query": "q"})
    assert r.status_code == 422


async def test_invalid_top_k_is_rejected() -> None:
    client, primary, replica = await build()
    epoch = primary.set_acl(T, D, {G1})
    replica.sync()
    r = await client.post("/search", json={"query": "q", "top_k": 0}, headers=headers(epoch))
    assert r.status_code == 422


    