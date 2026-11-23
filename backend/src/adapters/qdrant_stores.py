"""
Two collections, one per port, so the dense and lexical sides stay independently 
swappable (for example lexical to OpenSearch later). Both stores share one client, because local mode 
allows only one client per folder.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Sequence
from typing import Any

from fastembed import SparseTextEmbedding
from qdrant_client import AsyncQdrantClient, models

from domain.models import (
    Chunk,
    ChunkId,
    DocumentId,
    EmbeddedChunk,
    RetrievalSource,
    SearchHit,
    SecurityContext,
    TenantId,
)

_NAMESPACE = uuid.UUID("6f1c2a4e-0b7d-4c53-9a1e-3d5f8b2c7e10")


def _point_id(tenant_id: TenantId, chunk_id: ChunkId) -> str:
    """Qdrant ids must be uuid/int. uuid5 is deterministic, so retries overwrite (idempotent).
    The tenant is part of the key so two tenants can never collide on the same chunk_id."""
    return str(uuid.uuid5(_NAMESPACE, f"{tenant_id}\x1f{chunk_id}"))


def _slug(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


def _payload(c: Chunk) -> dict[str, Any]:
    return {
        "chunk_id": c.chunk_id,
        "tenant_id": c.tenant_id,
        "document_id": c.document_id,
        "version": c.version,
        "ordinal": c.ordinal,
        "text": c.text,
        "title": c.title,
        "section": c.section,
        "start_offset": c.start_offset,
        "end_offset": c.end_offset,
    }


def _hit(p: dict[str, Any], score: float, source: RetrievalSource) -> SearchHit:
    return SearchHit(
        chunk_id=ChunkId(p["chunk_id"]),
        tenant_id=TenantId(p["tenant_id"]),
        document_id=DocumentId(p["document_id"]),
        version=int(p["version"]),
        title=p["title"],
        section=p["section"],
        start_offset=int(p["start_offset"]),
        end_offset=int(p["end_offset"]),
        text=p["text"],
        score=score,
        source=source,
    )


def _tenant_filter(tenant_id: TenantId) -> models.Filter:
    # Mandatory on every query: the SecurityContext is the only way to reach search().
    return models.Filter(
        must=[models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id))]
    )


async def _ensure_indexes(client: AsyncQdrantClient, collection: str) -> None:
    for field in ("tenant_id", "document_id"):
        await client.create_payload_index(
            collection_name=collection,
            field_name=field,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )


async def _delete_below(
    client: AsyncQdrantClient,
    collection: str,
    tenant_id: TenantId,
    document_id: DocumentId,
    below_version: int,
) -> int:
    flt = models.Filter(
        must=[
            models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id)),
            models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id)),
            models.FieldCondition(key="version", range=models.Range(lt=below_version)),
        ]
    )
    n = (await client.count(collection_name=collection, count_filter=flt, exact=True)).count
    if n:
        await client.delete(
            collection_name=collection,
            points_selector=models.FilterSelector(filter=flt),
            wait=True,
        )
    return n


class QdrantVectorStore:
    """Dense index. wait=True on writes means upsert() returns only once the points are durable,
    which matters because the worker promotes right after."""

    def __init__(
        self, client: AsyncQdrantClient, index_version: str, dim: int, prefix: str = "rag"
    ) -> None:
        self._client = client
        self._index_version = index_version
        self._dim = dim
        self._collection = f"{prefix}_dense_{_slug(index_version)}"

    @property
    def index_version(self) -> str:
        return self._index_version

    async def ensure(self) -> None:
        if await self._client.collection_exists(self._collection):
            return
        await self._client.create_collection(
            collection_name=self._collection,
            vectors_config=models.VectorParams(size=self._dim, distance=models.Distance.COSINE),
        )
        await _ensure_indexes(self._client, self._collection)

    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        if not chunks:
            return
        await self._client.upsert(
            collection_name=self._collection,
            points=[
                models.PointStruct(
                    id=_point_id(item.chunk.tenant_id, item.chunk.chunk_id),
                    vector=list(item.vector),
                    payload=_payload(item.chunk),
                )
                for item in chunks
            ],
            wait=True,
        )

    async def search(
        self, ctx: SecurityContext, query_vector: Sequence[float], top_k: int
    ) -> list[SearchHit]:
        res = await self._client.query_points(
            collection_name=self._collection,
            query=list(query_vector),
            query_filter=_tenant_filter(ctx.tenant_id),
            limit=top_k,
            with_payload=True,
        )
        return [_hit(p.payload or {}, p.score, RetrievalSource.DENSE) for p in res.points]

    async def delete_document_versions(
        self, tenant_id: TenantId, document_id: DocumentId, *, below_version: int
    ) -> int:
        return await _delete_below(
            self._client, self._collection, tenant_id, document_id, below_version
        )


class QdrantLexicalStore:
    """BM25 via Qdrant sparse vectors (fastembed's Qdrant/bm25 model, IDF applied server-side).
    Note: IDF statistics are collection-wide, so they span tenants. Ranking is affected by other
    tenants' term frequencies; isolation of *content* is unaffected. Mention this trade-off."""

    def __init__(
        self,
        client: AsyncQdrantClient,
        prefix: str = "rag",
        model_name: str = "Qdrant/bm25",
        model: SparseTextEmbedding | None = None,
    ) -> None:
        self._client = client
        self._collection = f"{prefix}_lexical"
        self._model = model if model is not None else SparseTextEmbedding(model_name=model_name)

    @property
    def model(self) -> SparseTextEmbedding:
        return self._model

    async def ensure(self) -> None:
        if await self._client.collection_exists(self._collection):
            return
        await self._client.create_collection(
            collection_name=self._collection,
            vectors_config={},
            sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        await _ensure_indexes(self._client, self._collection)

    async def upsert(self, chunks: Sequence[Chunk]) -> None:
        if not chunks:
            return
        texts = [c.text for c in chunks]
        embeddings = await asyncio.to_thread(lambda: list(self._model.embed(texts)))
        await self._client.upsert(
            collection_name=self._collection,
            points=[
                models.PointStruct(
                    id=_point_id(c.tenant_id, c.chunk_id),
                    vector={
                        "bm25": models.SparseVector(
                            indices=e.indices.tolist(), values=e.values.tolist()
                        )
                    },
                    payload=_payload(c),
                )
                for c, e in zip(chunks, embeddings, strict=True)
            ],
            wait=True,
        )

    async def search(self, ctx: SecurityContext, query: str, top_k: int) -> list[SearchHit]:
        embedded = await asyncio.to_thread(lambda: list(self._model.query_embed(query)))
        if not embedded or embedded[0].indices.size == 0:
            return []
        q = models.SparseVector(
            indices=embedded[0].indices.tolist(), values=embedded[0].values.tolist()
        )
        res = await self._client.query_points(
            collection_name=self._collection,
            query=q,
            using="bm25",
            query_filter=_tenant_filter(ctx.tenant_id),
            limit=top_k,
            with_payload=True,
        )
        return [_hit(p.payload or {}, p.score, RetrievalSource.LEXICAL) for p in res.points]

    async def delete_document_versions(
        self, tenant_id: TenantId, document_id: DocumentId, *, below_version: int
    ) -> int:
        return await _delete_below(
            self._client, self._collection, tenant_id, document_id, below_version
        )
    



    