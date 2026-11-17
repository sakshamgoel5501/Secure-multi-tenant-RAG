from __future__ import annotations

import asyncio
from collections.abc import Collection, Sequence

from domain.errors import AuthzUnavailable
from domain.models import (
    AclSnapshot,
    Chunk,
    DocumentId,
    DocumentState,
    EmbeddedChunk,
    PromotionOutcome,
    SearchHit,
    SecurityContext,
    TenantId,
)
from domain.ports import LLM, AclReader, DocStateStore, LexicalStore, Reranker, VectorStore

COMPONENTS = frozenset({"dense", "lexical", "reranker", "llm", "state", "acl"})


class Faults:
    """Mutable fault switchboard shared by every wrapper."""

    def __init__(self) -> None:
        self.fail: set[str] = set()
        self.delay: dict[str, float] = {}

    def set(self, fail: Collection[str], delay: dict[str, float]) -> None:
        self.fail = set(fail)
        self.delay = dict(delay)

    def clear(self) -> None:
        self.fail = set()
        self.delay = {}

    async def hit(self, name: str) -> None:
        pause = self.delay.get(name, 0.0)
        if pause:
            await asyncio.sleep(pause)
        if name in self.fail:
            raise RuntimeError(f"chaos: {name} is down")


class ChaosVectorStore:
    def __init__(self, inner: VectorStore, faults: Faults) -> None:
        self._inner = inner
        self._faults = faults

    @property
    def index_version(self) -> str:
        return self._inner.index_version

    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        await self._inner.upsert(chunks)

    async def search(
        self, ctx: SecurityContext, query_vector: Sequence[float], top_k: int
    ) -> list[SearchHit]:
        await self._faults.hit("dense")
        return await self._inner.search(ctx, query_vector, top_k)

    async def delete_document_versions(
        self, tenant_id: TenantId, document_id: DocumentId, *, below_version: int
    ) -> int:
        return await self._inner.delete_document_versions(
            tenant_id, document_id, below_version=below_version
        )


class ChaosLexicalStore:
    def __init__(self, inner: LexicalStore, faults: Faults) -> None:
        self._inner = inner
        self._faults = faults

    async def upsert(self, chunks: Sequence[Chunk]) -> None:
        await self._inner.upsert(chunks)

    async def search(self, ctx: SecurityContext, query: str, top_k: int) -> list[SearchHit]:
        await self._faults.hit("lexical")
        return await self._inner.search(ctx, query, top_k)

    async def delete_document_versions(
        self, tenant_id: TenantId, document_id: DocumentId, *, below_version: int
    ) -> int:
        return await self._inner.delete_document_versions(
            tenant_id, document_id, below_version=below_version
        )


class ChaosReranker:
    def __init__(self, inner: Reranker, faults: Faults) -> None:
        self._inner = inner
        self._faults = faults

    async def rerank(self, query: str, hits: Sequence[SearchHit], top_k: int) -> list[SearchHit]:
        await self._faults.hit("reranker")
        return await self._inner.rerank(query, hits, top_k)


class ChaosLLM:
    def __init__(self, inner: LLM, faults: Faults) -> None:
        self._inner = inner
        self._faults = faults

    async def generate(self, system: str, user: str) -> str:
        await self._faults.hit("llm")
        return await self._inner.generate(system, user)


class ChaosAcl:
    def __init__(self, inner: AclReader, faults: Faults) -> None:
        self._inner = inner
        self._faults = faults

    async def acls_for(
        self,
        tenant_id: TenantId,
        document_ids: Collection[DocumentId],
        *,
        min_epoch: int,
    ) -> AclSnapshot:
        try:
            await self._faults.hit("acl")
        except RuntimeError as exc:
            raise AuthzUnavailable(str(exc)) from exc  # what the real adapter does on DB errors
        return await self._inner.acls_for(tenant_id, document_ids, min_epoch=min_epoch)


class ChaosDocState:
    """Only the query-path read (get_many) is faulty; ingestion keeps working."""

    def __init__(self, inner: DocStateStore, faults: Faults) -> None:
        self._inner = inner
        self._faults = faults

    async def record_seen(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> DocumentState:
        return await self._inner.record_seen(tenant_id, document_id, version)

    async def promote(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> PromotionOutcome:
        return await self._inner.promote(tenant_id, document_id, version)

    async def tombstone(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> DocumentState:
        return await self._inner.tombstone(tenant_id, document_id, version)

    async def get(self, tenant_id: TenantId, document_id: DocumentId) -> DocumentState | None:
        return await self._inner.get(tenant_id, document_id)

    async def get_many(
        self, tenant_id: TenantId, document_ids: Collection[DocumentId]
    ) -> dict[DocumentId, DocumentState]:
        await self._faults.hit("state")
        return await self._inner.get_many(tenant_id, document_ids)
    


    