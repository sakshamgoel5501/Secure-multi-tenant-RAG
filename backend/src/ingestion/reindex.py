from __future__ import annotations

import asyncio

from domain.models import DocumentEvent, EmbeddedChunk
from domain.ports import Chunker, Embedder, LexicalStore, VectorStore


class Reindexer:
    """Rewrites the chunks of ONE already-committed version into the indexes.

    It never touches the commit point (no record_seen, no promote). The normal worker can't
    do this, because for an already-active version it exits early as ALREADY_ACTIVE. Chunk IDs
    are deterministic, so running this twice is harmless.
    """

    def __init__(
        self,
        vectors: VectorStore,
        chunker: Chunker,
        embedder: Embedder,
        lexical: LexicalStore | None = None,
    ) -> None:
        self._vectors = vectors
        self._chunker = chunker
        self._embedder = embedder
        self._lexical = lexical

    async def reindex(self, event: DocumentEvent) -> int:
        chunks = self._chunker.chunk(
            event.tenant_id, event.document_id, event.version, event.title, event.text
        )
        embeddings = await self._embedder.embed([c.text for c in chunks])
        writes = [
            self._vectors.upsert(
                [EmbeddedChunk(c, v) for c, v in zip(chunks, embeddings, strict=True)]
            )
        ]
        if self._lexical is not None:
            writes.append(self._lexical.upsert(chunks))
        await asyncio.gather(*writes)
        return len(chunks)
    


    