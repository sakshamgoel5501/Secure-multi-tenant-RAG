import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis

from adapters.chaos import (
    ChaosAcl,
    ChaosDocState,
    ChaosLexicalStore,
    ChaosLLM,
    ChaosReranker,
    ChaosVectorStore,
    Faults,
)
from adapters.fake_llm import ExtractiveLLM
from adapters.fastembed_embedder import FastEmbedEmbedder
from adapters.fastembed_reranker import FastEmbedReranker
from adapters.gemini_llm import GeminiLLM
from adapters.postgres_acl import PostgresAclStore
from adapters.postgres_doc_state import PostgresDocStateStore
from adapters.postgres_scanner import PostgresStateScanner
from adapters.qdrant_stores import QdrantLexicalStore, QdrantVectorStore
from adapters.redis_bus import RedisEventBus
from adapters.resilient_llm import ResilientLLM
from adapters.simple_chunker import ParagraphChunker
from domain.ports import LLM, AclReader, DocStateStore, LexicalStore, Reranker, VectorStore
from ingestion.consumer import IngestionConsumer
from ingestion.worker import IngestionWorker
from serving.admin import admin_key_from_env, create_admin_router
from serving.answer_service import AnswerService
from serving.api import create_app
from serving.auth import jwt_identity
from serving.chaos_api import mount_chaos
from serving.query_service import QueryService

DSN = os.environ.get("RAG_PG_DSN", "postgresql://localhost/rag")
REDIS_URL = os.environ.get("RAG_REDIS_URL", "redis://localhost:6379/0")
CHAOS = os.environ.get("RAG_CHAOS") == "1"
ADMIN_KEY = admin_key_from_env(os.environ)  # exits at import time if enabled without a strong key


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


# --- real adapters ------------------------------------------------------------------------
state = PostgresDocStateStore(DSN)
acl = PostgresAclStore(DSN)
scanner = PostgresStateScanner(DSN)  # only started when the admin API is enabled
redis = Redis.from_url(REDIS_URL, decode_responses=True)
bus = RedisEventBus(redis)
qdrant = (
    AsyncQdrantClient(url=os.environ["QDRANT_URL"])
    if os.environ.get("QDRANT_URL")
    else AsyncQdrantClient(path="./qdrant_data")  # embedded: one process only, no --reload
)
embedder = FastEmbedEmbedder()
vectors = QdrantVectorStore(qdrant, embedder.model_version, embedder.dim)
lexical = QdrantLexicalStore(qdrant)
reranker = FastEmbedReranker()

raw_llm: LLM
if os.environ.get("GCP_PROJECT"):
    _tb = os.environ.get("RAG_GEMINI_THINKING_BUDGET", "0")  # "none" keeps the model default
    raw_llm = GeminiLLM(
        os.environ["GCP_PROJECT"],
        os.environ.get("GCP_LOCATION", "us-central1"),
        os.environ.get("RAG_GEMINI_MODEL", "gemini-2.5-flash"),
        thinking_budget=None if _tb.lower() == "none" else int(_tb),
    )
else:
    raw_llm = ExtractiveLLM()
print(f"[startup] LLM adapter: {type(raw_llm).__name__}")
if os.environ.get("GCP_PROJECT"):
    raw_llm = ResilientLLM(
        raw_llm,
        max_attempts=2,
        hedge_after=_env_float("RAG_LLM_HEDGE_AFTER", 1.5),
    )

# --- ingestion path always uses the real adapters -------------------------------------------
worker = IngestionWorker(state, vectors, ParagraphChunker(max_chars=400), embedder, lexical)
consumer = IngestionConsumer(bus, worker)

# --- query path: optionally wrapped in fault injectors --------------------------------------
faults = Faults()
q_state: DocStateStore = ChaosDocState(state, faults) if CHAOS else state
q_vectors: VectorStore = ChaosVectorStore(vectors, faults) if CHAOS else vectors
q_lexical: LexicalStore = ChaosLexicalStore(lexical, faults) if CHAOS else lexical
q_reranker: Reranker = ChaosReranker(reranker, faults) if CHAOS else reranker
q_acl: AclReader = ChaosAcl(acl, faults) if CHAOS else acl
llm: LLM = ChaosLLM(raw_llm, faults) if CHAOS else raw_llm

query_service = QueryService(
    q_state,
    q_vectors,
    embedder,
    q_acl,
    lexical=q_lexical,
    reranker=q_reranker,
    rerank_k=10,
    retrieval_timeout=_env_float("RAG_RETRIEVAL_TIMEOUT", 2.0),
    rerank_timeout=_env_float("RAG_RERANK_TIMEOUT", 2.0),
)
answer_service = AnswerService(
    query_service, llm, generation_timeout=_env_float("RAG_GENERATION_TIMEOUT", 10.0)
)

_secret = os.environ.get("RAG_JWT_SECRET")
identity = jwt_identity(_secret, acl) if _secret else None
print(f"[startup] identity: {'JWT, epoch from ACL store' if _secret else 'DEV HEADERS (insecure)'}")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await state.start()
    await acl.start()
    if ADMIN_KEY is not None:
        await scanner.start()
    await bus.ensure()
    await vectors.ensure()
    await lexical.ensure()
    await embedder.embed(["warm up"])
    await reranker.warm_up()
    try:
        await asyncio.wait_for(raw_llm.generate("Reply with OK.", "ping"), 20)
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] LLM warm-up failed (will retry on first request): {exc!r}")
    stop = asyncio.Event()
    task = asyncio.create_task(consumer.run_forever(stop))
    try:
        yield
    finally:
        stop.set()
        await task
        if ADMIN_KEY is not None:
            await scanner.close()
        await acl.close()
        await state.close()
        await redis.aclose()
        await qdrant.close()


app = create_app(query_service, lifespan=lifespan, answers=answer_service, identity=identity)
if CHAOS:
    mount_chaos(app, faults)
    print("[startup] WARNING: chaos endpoint mounted at /chaos (never enable in production)")
if ADMIN_KEY is not None:
    app.include_router(
        create_admin_router(
            state,
            scanner,
            acl,
            bus,
            admin_key=ADMIN_KEY,
            data_dir=Path(os.environ.get("RAG_DATA_DIR", "data")),
        )
    )
    print("[startup] admin API mounted at /admin (X-Admin-Key required)")


    