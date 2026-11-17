from __future__ import annotations

import asyncio

from domain.models import (
    DocumentEvent,
    EmbeddedChunk,
    Operation,
    PromotionOutcome,
)
from domain.ports import Chunker, DocStateStore, Embedder, LexicalStore, VectorStore


class IngestionWorker:
    """Applies one event at a time. Safe to call repeatedly with the same event."""

    def __init__(
        self,
        doc_state: DocStateStore,
        vectors: VectorStore,
        chunker: Chunker,
        embedder: Embedder,
        lexical: LexicalStore | None = None,
    ) -> None:
        self._state = doc_state
        self._vectors = vectors
        self._chunker = chunker
        self._embedder = embedder
        self._lexical = lexical

    async def handle(self, event: DocumentEvent) -> PromotionOutcome | None:
        if event.operation is Operation.DELETE:
            await self._state.tombstone(event.tenant_id, event.document_id, event.version)
            return None  # physical cleanup is left to a background job

        # 1. Announce the version. Monotonic and idempotent.
        state = await self._state.record_seen(event.tenant_id, event.document_id, event.version)

        # 2. Cheap early exit (optimization only; promote() is the real guard).
        if state.active_version is not None and event.version <= state.active_version:
            if event.version == state.active_version:
                await self._cleanup(event)
                return PromotionOutcome.ALREADY_ACTIVE
            return PromotionOutcome.STALE

        # 3. Expensive work, invisible to queries.
        chunks = self._chunker.chunk(
            event.tenant_id, event.document_id, event.version, event.title, event.text
        )
        vectors = await self._embedder.embed([c.text for c in chunks])
        if len(vectors) != len(chunks):
            raise ValueError("embedder returned a different number of vectors than chunks")

        # 4. Write both indexes in parallel with deterministic IDs (retry-safe).
        writes = [
            self._vectors.upsert([EmbeddedChunk(c, v) for c, v in zip(chunks, vectors, strict=True)])
        ]
        if self._lexical is not None:
            writes.append(self._lexical.upsert(chunks))
        await asyncio.gather(*writes)

        # 5. Commit point.
        outcome = await self._state.promote(event.tenant_id, event.document_id, event.version)

        # 6. Cleanup of older versions. Never a security dependency.
        if outcome is PromotionOutcome.PROMOTED:
            await self._cleanup(event)
        return outcome

    async def _cleanup(self, event: DocumentEvent) -> None:
        cleanups = [
            self._vectors.delete_document_versions(
                event.tenant_id, event.document_id, below_version=event.version
            )
        ]
        if self._lexical is not None:
            cleanups.append(
                self._lexical.delete_document_versions(
                    event.tenant_id, event.document_id, below_version=event.version
                )
            )
        await asyncio.gather(*cleanups)






        