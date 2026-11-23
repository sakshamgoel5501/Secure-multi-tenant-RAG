import json
from typing import Any

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

T, D = TenantId("t1"), DocumentId("d1")


async def client() -> tuple[httpx.AsyncClient, int]:
    state, vectors, embedder = InMemoryDocStateStore(), InMemoryVectorStore(), HashEmbedder()
    worker = IngestionWorker(state, vectors, ParagraphChunker(max_chars=200), embedder)
    await worker.handle(DocumentEvent(Operation.UPSERT, T, D, 1, "Leave", "Twenty days of leave."))
    primary = InMemoryAclPrimary()
    replica = InMemoryAclReplica(primary)
    epoch = primary.set_acl(T, D, {GroupId("g1")})
    replica.sync()
    svc = QueryService(state, vectors, embedder, replica)
    app = create_app(svc, answers=AnswerService(svc, ExtractiveLLM(delay=0)))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test"), epoch


def headers(epoch: int, group: str = "g1") -> dict[str, str]:
    return {"X-Tenant-Id": "t1", "X-User-Id": "u", "X-Groups": group, "X-Policy-Epoch": str(epoch)}


def parse(text: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in text.strip().split("\n\n"):
        head, data = block.split("\n")
        out.append((head.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


async def test_the_stream_carries_sources_deltas_and_a_final_answer() -> None:
    c, epoch = await client()
    r = await c.post("/ask/stream", json={"question": "how many days?"}, headers=headers(epoch))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    evs = parse(r.text)
    assert evs[0][0] == "sources" and evs[-1][0] == "final"
    assert "delta" in [n for n, _ in evs]
    assert evs[-1][1]["answer"] == "Twenty days of leave. [S1]" and evs[-1][1]["grounded"]


async def test_a_user_without_access_gets_no_sources_and_no_answer() -> None:
    c, epoch = await client()
    r = await c.post("/ask/stream", json={"question": "how many days?"}, headers=headers(epoch, "g2"))
    evs = parse(r.text)
    assert [n for n, _ in evs] == ["sources", "final"]
    assert evs[0][1]["sources"] == [] and not evs[-1][1]["grounded"]


async def test_a_lagging_permission_store_is_a_clean_503_before_any_stream() -> None:
    c, _ = await client()
    r = await c.post("/ask/stream", json={"question": "q"}, headers=headers(epoch=99))
    assert r.status_code == 503 and r.headers["content-type"].startswith("application/json")
    assert "epoch" not in r.text

    