"""
Run it with the server stopped, because embedded Qdrant allows only one process per folder.
"""

from __future__ import annotations

import argparse
import asyncio
import os

from qdrant_client import AsyncQdrantClient

from adapters.fastembed_embedder import FastEmbedEmbedder
from adapters.postgres_scanner import PostgresStateScanner
from adapters.qdrant_inspector import QdrantIndexInspector
from adapters.qdrant_stores import QdrantLexicalStore, QdrantVectorStore, _slug
from adapters.simple_chunker import ParagraphChunker
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
    embedder = FastEmbedEmbedder()
    vectors = QdrantVectorStore(qdrant, embedder.model_version, embedder.dim)
    lexical = QdrantLexicalStore(qdrant)
    await vectors.ensure()  # recreates empty collections if the folder was wiped
    await lexical.ensure()

    scanner = PostgresStateScanner(dsn)
    await scanner.start()

    # Stand-in for the real source of truth (object storage / the upstream system).
    corpus, _ = generate_corpus(tenants, docs, seed)
    source = {(d.tenant_id, d.document_id): d for d in corpus}
    reindexer = Reindexer(vectors, ParagraphChunker(max_chars=400), embedder, lexical)

    async def repair(tenant: TenantId, doc: DocumentId, version: int) -> bool:
        d = source.get((tenant, doc))
        if d is None or version != 1:  # the demo loader only ever creates version 1
            return False
        await reindexer.reindex(DocumentEvent(Operation.UPSERT, tenant, doc, version, d.title, d.text))
        return True

    reconciler = Reconciler(
        scanner,
        {
            "dense": QdrantIndexInspector(qdrant, f"rag_dense_{_slug(embedder.model_version)}"),
            "lexical": QdrantIndexInspector(qdrant, "rag_lexical"),
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



    
