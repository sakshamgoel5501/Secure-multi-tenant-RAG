from __future__ import annotations

from collections.abc import Collection
from typing import Protocol

from domain.models import DocumentId, DocumentState, GroupId, TenantId


class StateScanner(Protocol):
    """Enumerates the authoritative state. Used by background jobs, never on the query path."""

    async def list_tenants(self) -> list[TenantId]: ...

    async def list_states(self, tenant_id: TenantId) -> list[DocumentState]: ...


class IndexInspector(Protocol):
    """Looks inside one search index (dense or lexical) so it can be audited and cleaned."""

    async def list_versions(self, tenant_id: TenantId) -> dict[DocumentId, set[int]]:
        """Which versions of each document currently have chunks in this index."""
        ...

    async def delete_versions(
        self, tenant_id: TenantId, document_id: DocumentId, versions: Collection[int]
    ) -> int:
        """Physically delete exactly these versions. Returns how many were removed."""
        ...


class AclAdmin(Protocol):
    """Admin view of document ACLs: enumerate them and change them."""

    async def list_acls(self, tenant_id: TenantId) -> dict[DocumentId, frozenset[GroupId]]: ...

    async def set_acl(
        self, tenant_id: TenantId, document_id: DocumentId, groups: Collection[GroupId]
    ) -> int:
        """Replace a document's groups. Returns the new policy epoch."""
        ...


class DeadLetterInspector(Protocol):
    """Read-only view of the event bus's failure state."""

    async def pending_count(self) -> int: ...

    async def dlq_entries(self) -> list[dict[str, str]]: ...