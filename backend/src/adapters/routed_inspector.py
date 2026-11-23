from __future__ import annotations

from collections.abc import Callable, Collection

from qdrant_client import AsyncQdrantClient

from adapters.qdrant_inspector import QdrantIndexInspector
from domain.models import DocumentId, TenantId


class RoutedInspector:
    """Audit and cleanup view that follows each tenant to its own collection. A collection that
    doesn't exist yet (a silo tenant that never ingested anything) reads as empty."""

    def __init__(self, client: AsyncQdrantClient, collection_for: Callable[[str], str]) -> None:
        self._client = client
        self._collection_for = collection_for

    async def _inspector(self, tenant: str) -> QdrantIndexInspector | None:
        name = self._collection_for(tenant)
        if not await self._client.collection_exists(name):
            return None
        return QdrantIndexInspector(self._client, name)

    async def list_versions(self, tenant_id: TenantId) -> dict[DocumentId, set[int]]:
        insp = await self._inspector(tenant_id)
        return {} if insp is None else await insp.list_versions(tenant_id)

    async def delete_versions(
        self, tenant_id: TenantId, document_id: DocumentId, versions: Collection[int]
    ) -> int:
        insp = await self._inspector(tenant_id)
        return 0 if insp is None else await insp.delete_versions(tenant_id, document_id, versions)

    async def document_versions(self, tenant_id: TenantId, document_id: DocumentId) -> dict[int, int]:
        insp = await self._inspector(tenant_id)
        return {} if insp is None else await insp.document_versions(tenant_id, document_id)
    
    