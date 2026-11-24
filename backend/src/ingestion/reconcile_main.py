from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from qdrant_client import AsyncQdrantClient

from adapters.blob_factory import make_blob_store
from adapters.fastembed_embedder import FastEmbedEmbedder
from adapters.postgres_scanner import PostgresStateScanner
from adapters.qdrant_stores import QdrantLexicalStore, QdrantVectorStore
from adapters.routed_inspector import RoutedInspector
from adapters.simple_chunker import ParagraphChunker
from adapters.tenant_layout import TenantLayout
from adapters.tenant_routing import RoutedLexicalStore, RoutedVectorStore
from domain.models import DocumentEvent, DocumentId, Operation, TenantId
from ingestion.corpus import generate_corpus
from ingestion.reconciler import Reconciler
from ingestion.reindex import Reindexer


async def run(tenants: int, docs: int, seed: int) -> None:
    dsn = os.environ.get("RAG_PG_DSN", "postgresql://localhost/rag")
    qdrant = (
        AsyncQdrantClient(url=os.environ["QDRANT_URL"])
        if os.environ.get("QDRANT_URL")
        else AsyncQdrantClient(path="./qdrant_data")
    )
    silo = frozenset(t.strip() for t in os.environ.get("RAG_SILO_TENANTS", "").split(",") if t.strip())
    embedder = FastEmbedEmbedder()
    layout = TenantLayout(embedder.model_version, silo)
    shared_lexical = QdrantLexicalStore(qdrant)
    vectors = RoutedVectorStore(
        QdrantVectorStore(qdrant, embedder.model_version, embedder.dim), silo,
        lambda t: QdrantVectorStore(qdrant, embedder.model_version, embedder.dim, prefix=layout.prefix(t)),
    )  # fmt: skip
    lexical = RoutedLexicalStore(
        shared_lexical, silo,
        lambda t: QdrantLexicalStore(qdrant, prefix=layout.prefix(t), model=shared_lexical.model),
    )  # fmt: skip
    await vectors.ensure()  # recreates empty collections if the folder was wiped
    await lexical.ensure()

    scanner = PostgresStateScanner(dsn)
    await scanner.start()
    blobs = make_blob_store(Path(os.environ.get("RAG_BLOB_DIR", "data/blobs")), os.environ)

    # Stand-in for the upstream system, used for the synthetic corpus only.
    corpus, _ = generate_corpus(tenants, docs, seed)
    source = {(d.tenant_id, d.document_id): d for d in corpus}
    reindexer = Reindexer(vectors, ParagraphChunker(max_chars=400), embedder, lexical)

    async def repair(tenant: TenantId, doc: DocumentId, version: int) -> bool:
        text, meta = await blobs.get(tenant, doc, version, "text"), await blobs.get(tenant, doc, version, "meta")
        if text is not None and meta is not None:  # uploaded documents are rebuilt from the stored text
            title = str(json.loads(meta).get("title", doc))
            await reindexer.reindex(DocumentEvent(Operation.UPSERT, tenant, doc, version, title, text.decode()))
            return True
        d = source.get((tenant, doc))
        if d is None or version != 1:
            return False
        await reindexer.reindex(DocumentEvent(Operation.UPSERT, tenant, doc, version, d.title, d.text))
        return True

    reconciler = Reconciler(
        scanner,
        {
            "dense": RoutedInspector(qdrant, layout.dense_collection),
            "lexical": RoutedInspector(qdrant, layout.lexical_collection),
        },
        repair,
    )
    report = await reconciler.run()
    print(
        f"orphans deleted: {report.orphans_deleted}\n"
        f"missing (document, index) pairs: {len(report.missing)}\n"
        f"documents repaired: {report.repaired}"
    )
    await scanner.close()
    await qdrant.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Reconcile Postgres state with the search indexes")
    p.add_argument("--tenants", type=int, default=3)
    p.add_argument("--docs", type=int, default=40)
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()
    asyncio.run(run(args.tenants, args.docs, args.seed))


if __name__ == "__main__":
    main()

    