from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from adapters.fake_embedder import HashEmbedder
from adapters.fake_llm import ExtractiveLLM
from adapters.memory_acl import InMemoryAclPrimary, InMemoryAclReplica
from adapters.memory_doc_state import InMemoryDocStateStore
from adapters.memory_lexical import InMemoryLexicalStore
from adapters.memory_vector_store import InMemoryVectorStore
from adapters.overlap_reranker import OverlapReranker
from adapters.simple_chunker import ParagraphChunker
from domain.models import DocumentEvent, DocumentId, GroupId, Operation, TenantId
from ingestion.worker import IngestionWorker
from serving.answer_service import AnswerService
from serving.api import create_app
from serving.query_service import QueryService

T = TenantId("t1")

state = InMemoryDocStateStore()
vectors = InMemoryVectorStore()
lexical = InMemoryLexicalStore()
embedder = HashEmbedder()
worker = IngestionWorker(state, vectors, ParagraphChunker(max_chars=200), embedder, lexical)

primary = InMemoryAclPrimary()
replica = InMemoryAclReplica(primary)

DOCS = {
    "leave": ("Leave policy", "Employees get 20 days of paid leave per year."),
    "sec": ("Security ticket", "Ticket ENG-4821 was escalated to the security team."),
    "menu": ("Cafeteria", "The cafeteria menu changes every week."),
}
for doc_id in DOCS:
    primary.set_acl(T, DocumentId(doc_id), {GroupId("g1")})
replica.sync()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    for doc_id, (title, text) in DOCS.items():
        await worker.handle(DocumentEvent(Operation.UPSERT, T, DocumentId(doc_id), 1, title, text))
    yield


query_service = QueryService(
    state, vectors, embedder, replica, lexical=lexical, reranker=OverlapReranker()
)
answer_service = AnswerService(query_service, ExtractiveLLM())
app = create_app(query_service, lifespan=lifespan, answers=answer_service)




