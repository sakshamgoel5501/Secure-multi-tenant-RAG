"""
Runs each failure scenario against an in-memory stack with tight timeouts
"""

import httpx
import pytest

from adapters.chaos import (
    ChaosAcl,
    ChaosDocState,
    ChaosLexicalStore,
    ChaosLLM,
    ChaosReranker,
    ChaosVectorStore,
    Faults,
)
from adapters.fake_embedder import HashEmbedder
from adapters.fake_llm import ExtractiveLLM
from adapters.memory_acl import InMemoryAclPrimary, InMemoryAclReplica
from adapters.memory_doc_state import InMemoryDocStateStore
from adapters.memory_lexical import InMemoryLexicalStore
from adapters.memory_vector_store import InMemoryVectorStore
from adapters.overlap_reranker import OverlapReranker
from adapters.simple_chunker import ParagraphChunker
from domain.models import DocumentEvent, Operation
from eval.chaos import Scenario, default_scenarios, run_scenarios
from ingestion.corpus import GoldenQuery, generate_corpus
from ingestion.worker import IngestionWorker
from serving.answer_service import AnswerService
from serving.api import create_app
from serving.chaos_api import mount_chaos
from serving.query_service import QueryService


async def build() -> tuple[httpx.AsyncClient, GoldenQuery]:
    corpus, golden = generate_corpus(2, 10, seed=1)
    faults = Faults()
    state = InMemoryDocStateStore()
    vectors = InMemoryVectorStore()
    lexical = InMemoryLexicalStore()
    embedder = HashEmbedder()
    worker = IngestionWorker(state, vectors, ParagraphChunker(max_chars=400), embedder, lexical)
    primary = InMemoryAclPrimary()
    replica = InMemoryAclReplica(primary)
    for d in corpus:
        await worker.handle(
            DocumentEvent(Operation.UPSERT, d.tenant_id, d.document_id, 1, d.title, d.text)
        )
        primary.set_acl(d.tenant_id, d.document_id, d.groups)
    replica.sync()

    service = QueryService(
        ChaosDocState(state, faults),
        ChaosVectorStore(vectors, faults),
        embedder,
        ChaosAcl(replica, faults),
        lexical=ChaosLexicalStore(lexical, faults),
        reranker=ChaosReranker(OverlapReranker(), faults),
        retrieval_timeout=0.2,
        rerank_timeout=0.2,
    )
    answers = AnswerService(service, ChaosLLM(ExtractiveLLM(), faults), generation_timeout=0.2)
    app = create_app(service, answers=answers)
    mount_chaos(app, faults)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, next(g for g in golden if g.answerable)


@pytest.mark.parametrize("scenario", default_scenarios(delay=1.0), ids=lambda s: s.name)
async def test_failure_scenario_behaves_as_designed(scenario: Scenario) -> None:
    client, golden = await build()
    [result] = await run_scenarios(client, [scenario], golden, repeats=2)
    assert result.ok, result.detail


    
