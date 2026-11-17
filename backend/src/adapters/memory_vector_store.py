from __future__ import annotations

import math
from collections.abc import Sequence

from domain.models import (
    ChunkId,
    DocumentId,
    EmbeddedChunk,
    RetrievalSource,
    SearchHit,
    SecurityContext,
    TenantId,
)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class InMemoryVectorStore:
    """Brute-force fake. Rows are keyed by (tenant, chunk_id) so tenants can never collide."""

    def __init__(self, index_version: str = "mem-v1") -> None:
        self._index_version = index_version
        self._rows: dict[tuple[TenantId, ChunkId], EmbeddedChunk] = {}

    @property
    def index_version(self) -> str:
        return self._index_version

    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        for item in chunks:
            self._rows[(item.chunk.tenant_id, item.chunk.chunk_id)] = item  # idempotent

    async def search(
        self, ctx: SecurityContext, query_vector: Sequence[float], top_k: int
    ) -> list[SearchHit]:
        scored = [
            (_cosine(query_vector, row.vector), row.chunk)
            for row in self._rows.values()
            if row.chunk.tenant_id == ctx.tenant_id  # mandatory tenant filter
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            SearchHit(
                chunk_id=c.chunk_id,
                tenant_id=c.tenant_id,
                document_id=c.document_id,
                version=c.version,
                title=c.title,
                section=c.section,
                start_offset=c.start_offset,
                end_offset=c.end_offset,
                text=c.text,
                score=score,
                source=RetrievalSource.DENSE,
            )
            for score, c in scored[:top_k]
        ]

    async def delete_document_versions(
        self, tenant_id: TenantId, document_id: DocumentId, *, below_version: int
    ) -> int:
        doomed = [
            key
            for key, row in self._rows.items()
            if row.chunk.tenant_id == tenant_id
            and row.chunk.document_id == document_id
            and row.chunk.version < below_version
        ]
        for key in doomed:
            del self._rows[key]
        return len(doomed)
    

    