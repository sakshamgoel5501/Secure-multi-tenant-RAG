"""
Same app, real components. Without GCP_PROJECT set, it uses the extractive fake LLM, so you can test 
retrieval before touching GCP.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from qdrant_client import AsyncQdrantClient

from adapters.fake_llm import ExtractiveLLM
from adapters.fastembed_embedder import FastEmbedEmbedder
from adapters.fastembed_reranker import FastEmbedReranker
from adapters.gemini_llm import GeminiLLM
from adapters.memory_acl import InMemoryAclPrimary, InMemoryAclReplica
from adapters.postgres_doc_state import PostgresDocStateStore
from adapters.qdrant_stores import QdrantLexicalStore, QdrantVectorStore
from adapters.simple_chunker import ParagraphChunker
from domain.models import DocumentEvent, DocumentId, GroupId, Operation, TenantId
from domain.ports import LLM
from ingestion.worker import IngestionWorker
from serving.answer_service import AnswerService
from serving.api import create_app
from serving.query_service import QueryService

T = TenantId("t1")

DOCS = {
    "leave": ("Leave policy", "Employees get 20 days of paid leave per year."),
    "sec": ("Security ticket", "Ticket ENG-4821 was escalated to the security team."),
    "menu": ("Cafeteria", "The cafeteria menu changes every week."),
    "travel": (
        "Travel policy",
        "Flights over 6 hours may be booked in premium economy with manager approval.",
    ),
    "oncall": (
        "On-call",
        "The on-call engineer rotates every Monday and carries the pager for seven days.",
    ),
}

# --- adapters -------------------------------------------------------------------------------
state = PostgresDocStateStore(os.environ.get("RAG_PG_DSN", "postgresql://localhost/rag"))
qdrant = (
    AsyncQdrantClient(url=os.environ["QDRANT_URL"])
    if os.environ.get("QDRANT_URL")
    else AsyncQdrantClient(path="./qdrant_data")  # embedded mode: one process only, no --reload
)
embedder = FastEmbedEmbedder()
vectors = QdrantVectorStore(qdrant, embedder.model_version, embedder.dim)
lexical = QdrantLexicalStore(qdrant)
reranker = FastEmbedReranker()

llm: LLM
if os.environ.get("GCP_PROJECT"):
    llm = GeminiLLM(
        os.environ["GCP_PROJECT"],
        os.environ.get("GCP_LOCATION", "us-central1"),
        os.environ.get("RAG_GEMINI_MODEL", "gemini-2.5-flash"),
    )
else:
    llm = ExtractiveLLM()

print(f"[startup] LLM adapter: {type(llm).__name__}")

# ACLs are still in-memory (Postgres ACL store and SpiceDB come later).
primary = InMemoryAclPrimary()
replica = InMemoryAclReplica(primary)
for doc_id in DOCS:
    primary.set_acl(T, DocumentId(doc_id), {GroupId("g1")})
replica.sync()

worker = IngestionWorker(state, vectors, ParagraphChunker(max_chars=400), embedder, lexical)

# Dev-friendly timeouts for CPU models on a laptop. Real budgets come from Phase 6 measurements.
query_service = QueryService(
    state,
    vectors,
    embedder,
    replica,
    lexical=lexical,
    reranker=reranker,
    rerank_k=10,
    retrieval_timeout=2.0,
    rerank_timeout=2.0,
)
answer_service = AnswerService(query_service, llm, generation_timeout=10.0)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await state.start()
    await vectors.ensure()
    await lexical.ensure()
    await embedder.embed(["warm up"])
    await reranker.warm_up()
    for doc_id, (title, text) in DOCS.items():
        # Idempotent: on restart this is ALREADY_ACTIVE and rewrites nothing.
        await worker.handle(DocumentEvent(Operation.UPSERT, T, DocumentId(doc_id), 1, title, text))
    try:
        yield
    finally:
        await state.close()
        await qdrant.close()


app = create_app(query_service, lifespan=lifespan, answers=answer_service)

