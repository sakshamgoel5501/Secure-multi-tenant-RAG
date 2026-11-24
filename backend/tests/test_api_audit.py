import asyncio

import httpx

from adapters.fake_embedder import HashEmbedder
from adapters.fake_llm import ExtractiveLLM
from adapters.memory_acl import InMemoryAclPrimary, InMemoryAclReplica
from adapters.memory_audit import InMemoryAuditLog
from adapters.memory_doc_state import InMemoryDocStateStore
from adapters.memory_vector_store import InMemoryVectorStore
from adapters.simple_chunker import ParagraphChunker
from domain.models import DocumentEvent, DocumentId, GroupId, Operation, TenantId
from ingestion.worker import IngestionWorker
from serving.answer_service import AnswerService
from serving.api import create_app
from serving.query_service import QueryService

T, D = TenantId("t1"), DocumentId("d1")


async def test_queries_are_audited_by_shape_never_by_text() -> None:
    state, vectors, embedder = InMemoryDocStateStore(), InMemoryVectorStore(), HashEmbedder()
    worker = IngestionWorker(state, vectors, ParagraphChunker(max_chars=200), embedder)
    await worker.handle(DocumentEvent(Operation.UPSERT, T, D, 1, "Leave", "Twenty days of leave."))
    primary = InMemoryAclPrimary()
    replica = InMemoryAclReplica(primary)
    epoch = primary.set_acl(T, D, {GroupId("g1")})
    replica.sync()
    audit = InMemoryAuditLog()
    svc = QueryService(state, vectors, embedder, replica)
    app = create_app(svc, answers=AnswerService(svc, ExtractiveLLM(delay=0)), audit=audit)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    h = {"X-Tenant-Id": "t1", "X-User-Id": "u", "X-Groups": "g1", "X-Policy-Epoch": str(epoch)}

    question = "how many days of leave?"
    await c.post("/search", json={"query": question}, headers=h)
    await c.post("/ask", json={"question": question}, headers=h)
    await asyncio.sleep(0.05)

    assert [e.action for e in audit.entries] == ["query.search", "query.ask"]
    assert audit.entries[0].detail == {"chars": len(question), "hits": 1}
    assert audit.entries[1].detail["grounded"] is True
    assert (audit.entries[0].actor, audit.entries[0].tenant, audit.entries[0].role) == ("u", "t1", "user")
    assert "leave" not in str([(e.target, e.detail) for e in audit.entries])


    