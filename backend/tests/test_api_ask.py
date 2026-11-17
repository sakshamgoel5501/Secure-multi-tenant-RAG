import httpx

from adapters.fake_embedder import HashEmbedder
from adapters.fake_llm import ExtractiveLLM
from adapters.memory_acl import InMemoryAclPrimary, InMemoryAclReplica
from adapters.memory_doc_state import InMemoryDocStateStore
from adapters.memory_vector_store import InMemoryVectorStore
from adapters.simple_chunker import ParagraphChunker
from domain.models import DocumentEvent, DocumentId, GroupId, Operation, TenantId
from ingestion.worker import IngestionWorker
from serving.answer_service import AnswerService
from serving.api import create_app
from serving.query_service import QueryService

T = TenantId("t1")
D = DocumentId("d1")


async def client() -> tuple[httpx.AsyncClient, int]:
    state = InMemoryDocStateStore()
    vectors = InMemoryVectorStore()
    embedder = HashEmbedder()
    worker = IngestionWorker(state, vectors, ParagraphChunker(max_chars=200), embedder)
    await worker.handle(DocumentEvent(Operation.UPSERT, T, D, 1, "Leave", "Twenty days of leave."))
    primary = InMemoryAclPrimary()
    replica = InMemoryAclReplica(primary)
    epoch = primary.set_acl(T, D, {GroupId("g1")})
    replica.sync()
    svc = QueryService(state, vectors, embedder, replica)
    app = create_app(svc, answers=AnswerService(svc, ExtractiveLLM()))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test"), epoch


def headers(epoch: int, group: str) -> dict[str, str]:
    return {
        "X-Tenant-Id": "t1",
        "X-User-Id": "u1",
        "X-Groups": group,
        "X-Policy-Epoch": str(epoch),
    }


async def test_ask_returns_cited_answer() -> None:
    c, epoch = await client()
    r = await c.post("/ask", json={"question": "how many days?"}, headers=headers(epoch, "g1"))
    body = r.json()
    assert r.status_code == 200
    assert body["grounded"] is True
    assert body["answer"] == "Twenty days of leave. [S1]"
    assert body["citations"][0]["document_id"] == "d1"


async def test_ask_without_access_gets_no_information() -> None:
    c, epoch = await client()
    r = await c.post("/ask", json={"question": "how many days?"}, headers=headers(epoch, "g2"))
    assert r.status_code == 200
    assert r.json()["grounded"] is False
    assert r.json()["citations"] == []


    