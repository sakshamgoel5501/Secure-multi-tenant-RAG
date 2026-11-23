from __future__ import annotations

import asyncio
from collections.abc import Callable, Collection, Sequence
from typing import Generic, Protocol, TypeVar

from domain.models import Chunk, DocumentId, EmbeddedChunk, SearchHit, SecurityContext, TenantId
from domain.ports import LexicalStore, VectorStore


class _Ensured(Protocol):
    async def ensure(self) -> None: ...


class EnsuredVectorStore(VectorStore, Protocol):
    async def ensure(self) -> None: ...


class EnsuredLexicalStore(LexicalStore, Protocol):
    async def ensure(self) -> None: ...


S = TypeVar("S", bound=_Ensured)


class _Silos(Generic[S]):
    """Creates each silo tenant's store on first use, and makes sure its collections exist."""

    def __init__(self, tenants: Collection[str], make: Callable[[TenantId], S]) -> None:
        self.tenants = frozenset(tenants)
        self._make = make
        self._stores: dict[str, S] = {}
        self._lock = asyncio.Lock()

    async def get(self, tenant: str) -> S | None:
        if tenant not in self.tenants:
            return None
        store = self._stores.get(tenant)
        if store is None:
            async with self._lock:
                store = self._stores.get(tenant)
                if store is None:
                    store = self._make(TenantId(tenant))
                    await store.ensure()
                    self._stores[tenant] = store
        return store


class RoutedVectorStore:
    def __init__(
        self,
        shared: EnsuredVectorStore,
        silo_tenants: Collection[str],
        make: Callable[[TenantId], EnsuredVectorStore],
    ) -> None:
        self._shared = shared
        self._silos: _Silos[EnsuredVectorStore] = _Silos(silo_tenants, make)

    @property
    def index_version(self) -> str:
        return self._shared.index_version

    async def ensure(self) -> None:
        await self._shared.ensure()
        for tenant in sorted(self._silos.tenants):
            await self._silos.get(tenant)

    async def _store(self, tenant: str) -> VectorStore:
        silo = await self._silos.get(tenant)
        return silo if silo is not None else self._shared

    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        groups: dict[TenantId, list[EmbeddedChunk]] = {}
        for item in chunks:
            groups.setdefault(item.chunk.tenant_id, []).append(item)
        for tenant, items in groups.items():
            await (await self._store(tenant)).upsert(items)

    async def search(
        self, ctx: SecurityContext, query_vector: Sequence[float], top_k: int
    ) -> list[SearchHit]:
        return await (await self._store(ctx.tenant_id)).search(ctx, query_vector, top_k)

    async def delete_document_versions(
        self, tenant_id: TenantId, document_id: DocumentId, *, below_version: int
    ) -> int:
        store = await self._store(tenant_id)
        return await store.delete_document_versions(tenant_id, document_id, below_version=below_version)


class RoutedLexicalStore:
    def __init__(
        self,
        shared: EnsuredLexicalStore,
        silo_tenants: Collection[str],
        make: Callable[[TenantId], EnsuredLexicalStore],
    ) -> None:
        self._shared = shared
        self._silos: _Silos[EnsuredLexicalStore] = _Silos(silo_tenants, make)

    async def ensure(self) -> None:
        await self._shared.ensure()
        for tenant in sorted(self._silos.tenants):
            await self._silos.get(tenant)

    async def _store(self, tenant: str) -> LexicalStore:
        silo = await self._silos.get(tenant)
        return silo if silo is not None else self._shared

    async def upsert(self, chunks: Sequence[Chunk]) -> None:
        groups: dict[TenantId, list[Chunk]] = {}
        for c in chunks:
            groups.setdefault(c.tenant_id, []).append(c)
        for tenant, items in groups.items():
            await (await self._store(tenant)).upsert(items)

    async def search(self, ctx: SecurityContext, query: str, top_k: int) -> list[SearchHit]:
        return await (await self._store(ctx.tenant_id)).search(ctx, query, top_k)

    async def delete_document_versions(
        self, tenant_id: TenantId, document_id: DocumentId, *, below_version: int
    ) -> int:
        store = await self._store(tenant_id)
        return await store.delete_document_versions(tenant_id, document_id, below_version=below_version)
    
    