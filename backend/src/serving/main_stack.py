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
from adapters.file_parsers import DefaultFileParser
from adapters.gemini_llm import GeminiLLM
from adapters.llm_decomposer import LLMDecomposer
from adapters.local_blobs import LocalBlobStore
from adapters.postgres_accounts import PostgresAccountStore
from adapters.postgres_acl import PostgresAclStore
from adapters.postgres_audit import PostgresAuditLog
from adapters.postgres_doc_state import PostgresDocStateStore
from adapters.postgres_scanner import PostgresStateScanner
from adapters.qdrant_stores import QdrantLexicalStore, QdrantVectorStore
from adapters.redis_bus import RedisEventBus
from adapters.resilient_llm import ResilientLLM
from adapters.routed_inspector import RoutedInspector
from adapters.simple_chunker import ParagraphChunker
from adapters.tenant_layout import TenantLayout
from adapters.tenant_routing import RoutedLexicalStore, RoutedVectorStore
from domain.ports import LLM, AclReader, DocStateStore, LexicalStore, Reranker, VectorStore
from ingestion.consumer import IngestionConsumer
from ingestion.purge import Purger
from ingestion.reconciler import Reconciler
from ingestion.scheduler import run_periodically
from ingestion.worker import IngestionWorker
from serving.admin import admin_key_from_env, create_admin_router
from serving.admin_users import create_users_router
from serving.answer_service import AnswerService
from serving.api import create_app
from serving.auth import jwt_identity
from serving.auth_api import create_auth_router
from serving.auth_service import AuthService
from serving.bootstrap import ensure_bootstrap_admin
from serving.chaos_api import mount_chaos
from serving.planner import PlannedRetriever
from serving.query_service import QueryService, Retriever

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
SILO_TENANTS = frozenset(t.strip() for t in os.environ.get("RAG_SILO_TENANTS", "").split(",") if t.strip())
layout = TenantLayout(embedder.model_version, SILO_TENANTS)
shared_lexical = QdrantLexicalStore(qdrant)
vectors = RoutedVectorStore(
    QdrantVectorStore(qdrant, embedder.model_version, embedder.dim),
    SILO_TENANTS,
    lambda t: QdrantVectorStore(qdrant, embedder.model_version, embedder.dim, prefix=layout.prefix(t)),
)
lexical = RoutedLexicalStore(
    shared_lexical,
    SILO_TENANTS,
    lambda t: QdrantLexicalStore(qdrant, prefix=layout.prefix(t), model=shared_lexical.model),
)
print(f"[startup] dedicated collections for: {', '.join(sorted(SILO_TENANTS)) or 'no tenants (shared pool)'}")
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

indexes = {
    "dense": RoutedInspector(qdrant, layout.dense_collection),
    "lexical": RoutedInspector(qdrant, layout.lexical_collection),
}
blobs = LocalBlobStore(Path(os.environ.get("RAG_BLOB_DIR", "data/blobs")))
purger = Purger(state, acl, indexes, bus, blobs=blobs)
reconciler = Reconciler(scanner, indexes)  # no repair function: it only removes what is unreachable
audit = PostgresAuditLog(DSN)
RECONCILE_INTERVAL = _env_float("RAG_RECONCILE_INTERVAL", 600.0)  # seconds; 0 turns it off


async def reconcile_job() -> None:
    report = await reconciler.run()
    if report.orphans_deleted:
        print(f"[reconcile] removed {report.orphans_deleted} unreachable chunks")

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
retriever: Retriever = (
    query_service
    if os.environ.get("RAG_PLANNER", "1") == "0"
    else PlannedRetriever(
        query_service, LLMDecomposer(llm), timeout=_env_float("RAG_DECOMPOSE_TIMEOUT", 2.0)
    )
)
answer_service = AnswerService(
    retriever, llm, generation_timeout=_env_float("RAG_GENERATION_TIMEOUT", 10.0)
)

_secret = os.environ.get("RAG_JWT_SECRET")
accounts = PostgresAccountStore(DSN)
auth_service = AuthService(accounts, audit, _secret, ADMIN_KEY) if _secret else None
identity = jwt_identity(_secret, acl, accounts=accounts) if _secret else None
NEEDS_ACCOUNTS = _secret is not None or ADMIN_KEY is not None
print(f"[startup] identity: {'accounts (username and password)' if _secret else 'DEV HEADERS (insecure)'}")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await state.start()
    await acl.start()
    if NEEDS_ACCOUNTS:
        await accounts.start()
        await audit.start()
        if _secret:
            await ensure_bootstrap_admin(
                accounts,
                os.environ.get("RAG_BOOTSTRAP_ADMIN_USER"),
                os.environ.get("RAG_BOOTSTRAP_ADMIN_PASSWORD"),
            )
    if ADMIN_KEY is not None or RECONCILE_INTERVAL > 0:
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
    tasks = [asyncio.create_task(consumer.run_forever(stop))]
    if RECONCILE_INTERVAL > 0:
        tasks.append(asyncio.create_task(run_periodically(reconcile_job, RECONCILE_INTERVAL, stop)))
    try:
        yield
    finally:
        stop.set()
        await asyncio.gather(*tasks)
        if ADMIN_KEY is not None or RECONCILE_INTERVAL > 0:
            await scanner.close()
        if NEEDS_ACCOUNTS:
            await accounts.close()
            await audit.close()
        await acl.close()
        await state.close()
        await redis.aclose()
        await qdrant.close()


app = create_app(query_service, lifespan=lifespan, answers=answer_service, identity=identity)
if CHAOS:
    mount_chaos(app, faults)
    print("[startup] WARNING: chaos endpoint mounted at /chaos (never enable in production)")
if auth_service is not None:
    app.include_router(create_auth_router(auth_service))
if ADMIN_KEY is not None:
    app.include_router(
        create_admin_router(
            state,
            scanner,
            acl,
            bus,
            admin_key=ADMIN_KEY,
            data_dir=Path(os.environ.get("RAG_DATA_DIR", "data")),
            audit=audit,
            publisher=bus,
            purger=purger,
            accounts=accounts,
            searcher=query_service.retrieve,
            epochs=acl,
            blobs=blobs, 
            parser=DefaultFileParser(),
        )
    )
    app.include_router(create_users_router(accounts, audit, admin_key=ADMIN_KEY))
    print("[startup] admin API mounted at /admin (signed administrator accounts only)")


    