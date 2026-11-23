from __future__ import annotations

from domain.models import DocumentId, TenantId
from domain.ops_ports import BlobInfo

_Key = tuple[TenantId, DocumentId]


class InMemoryBlobStore:
    def __init__(self) -> None:
        self.data: dict[_Key, dict[tuple[int, str], bytes]] = {}
        self.fail = False  # tests flip this to simulate an outage

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("file store down")

    async def put(self, tenant_id: TenantId, document_id: DocumentId, version: int, kind: str, data: bytes) -> None:
        self._check()
        self.data.setdefault((tenant_id, document_id), {})[(version, kind)] = data

    async def get(self, tenant_id: TenantId, document_id: DocumentId, version: int, kind: str) -> bytes | None:
        self._check()
        return self.data.get((tenant_id, document_id), {}).get((version, kind))

    async def list_blobs(self, tenant_id: TenantId, document_id: DocumentId) -> list[BlobInfo]:
        items = self.data.get((tenant_id, document_id), {})
        return [BlobInfo(v, k, len(b)) for (v, k), b in sorted(items.items())]

    async def delete_document(self, tenant_id: TenantId, document_id: DocumentId) -> int:
        return len(self.data.pop((tenant_id, document_id), {}))
    

    