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
HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u", "X-Groups": "g1", "X-Policy-Epoch": "0"}


async def client() -> httpx.AsyncClient:
    state = InMemoryDocStateStore()
    vectors = InMemoryVectorStore()
    embedder = HashEmbedder()
    worker = IngestionWorker(state, vectors, ParagraphChunker(max_chars=200), embedder)
    await worker.handle(DocumentEvent(Operation.UPSERT, T, D, 1, "doc", "aaa one"))
    primary = InMemoryAclPrimary()
    replica = InMemoryAclReplica(primary)
    primary.set_acl(T, D, {GroupId("g1")})
    replica.sync()
    app = create_app(QueryService(state, vectors, embedder, replica))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_server_timing_header_lists_stages() -> None:
    c = await client()
    r = await c.post("/search", json={"query": "q"}, headers=HEADERS)
    timing = r.headers["Server-Timing"]
    for stage in ("embed", "dense", "state", "acl", "total"):
        assert f"{stage};dur=" in timing


async def test_stats_endpoint_aggregates_requests() -> None:
    c = await client()
    await c.post("/search", json={"query": "q"}, headers=HEADERS)
    snap = (await c.get("/stats")).json()
    assert snap["latency_ms"]["/search:total"]["n"] == 1
    assert snap["status"]["/search:200"] == 1


    