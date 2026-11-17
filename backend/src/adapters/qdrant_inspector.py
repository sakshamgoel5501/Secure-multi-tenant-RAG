from __future__ import annotations

from collections.abc import Collection
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from domain.models import DocumentId, TenantId


def _tenant_cond(tenant_id: TenantId) -> models.FieldCondition:
    return models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id))


class QdrantIndexInspector:
    """Audit and cleanup view over ONE Qdrant collection (dense and lexical each get their own)."""

    def __init__(self, client: AsyncQdrantClient, collection: str) -> None:
        self._client = client
        self._collection = collection

    async def list_versions(self, tenant_id: TenantId) -> dict[DocumentId, set[int]]:
        flt = models.Filter(must=[_tenant_cond(tenant_id)])
        out: dict[DocumentId, set[int]] = {}
        offset: Any = None
        while True:
            points, offset = await self._client.scroll(
                collection_name=self._collection,
                scroll_filter=flt,
                limit=500,
                offset=offset,
                with_payload=["document_id", "version"],
                with_vectors=False,
            )
            for p in points:
                payload = p.payload or {}
                out.setdefault(DocumentId(payload["document_id"]), set()).add(
                    int(payload["version"])
                )
            if offset is None:
                return out

    async def delete_versions(
        self, tenant_id: TenantId, document_id: DocumentId, versions: Collection[int]
    ) -> int:
        if not versions:
            return 0
        flt = models.Filter(
            must=[
                _tenant_cond(tenant_id),
                models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id)),
                models.FieldCondition(key="version", match=models.MatchAny(any=sorted(versions))),
            ]
        )
        n = (
            await self._client.count(collection_name=self._collection, count_filter=flt, exact=True)
        ).count
        if n:
            await self._client.delete(
                collection_name=self._collection,
                points_selector=models.FilterSelector(filter=flt),
                wait=True,
            )
        return n
    


    