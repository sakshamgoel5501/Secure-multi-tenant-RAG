from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

from domain.models import (
    Chunk,
    ChunkId,
    DocumentId,
    RetrievalSource,
    SearchHit,
    SecurityContext,
    TenantId,
)

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class InMemoryLexicalStore:
    """Brute-force BM25 fake. Rows are keyed by (tenant, chunk_id); scores are per tenant."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._rows: dict[tuple[TenantId, ChunkId], Chunk] = {}

    async def upsert(self, chunks: Sequence[Chunk]) -> None:
        for c in chunks:
            self._rows[(c.tenant_id, c.chunk_id)] = c

    async def search(self, ctx: SecurityContext, query: str, top_k: int) -> list[SearchHit]:
        rows = [c for c in self._rows.values() if c.tenant_id == ctx.tenant_id]
        q_terms = set(_tokens(query))
        if not rows or not q_terms:
            return []

        docs = [Counter(_tokens(c.text)) for c in rows]
        lengths = [sum(d.values()) for d in docs]
        avg_len = sum(lengths) / len(lengths) or 1.0
        n = len(rows)

        scored: list[tuple[float, Chunk]] = []
        for chunk, tf, length in zip(rows, docs, lengths, strict=True):
            score = 0.0
            for term in q_terms:
                f = tf.get(term, 0)
                if f == 0:
                    continue
                df = sum(1 for d in docs if term in d)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                norm = f + self._k1 * (1 - self._b + self._b * length / avg_len)
                score += idf * f * (self._k1 + 1) / norm
            if score > 0:
                scored.append((score, chunk))

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
                score=s,
                source=RetrievalSource.LEXICAL,
            )
            for s, c in scored[:top_k]
        ]

    async def delete_document_versions(
        self, tenant_id: TenantId, document_id: DocumentId, *, below_version: int
    ) -> int:
        doomed = [
            key
            for key, c in self._rows.items()
            if c.tenant_id == tenant_id
            and c.document_id == document_id
            and c.version < below_version
        ]
        for key in doomed:
            del self._rows[key]
        return len(doomed)
    
    