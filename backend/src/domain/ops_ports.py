from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any, Protocol

from domain.accounts import Account
from domain.models import DocumentEvent, DocumentId, DocumentState, GroupId, TenantId


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


class EventPublisher(Protocol):
    """Puts a document event on the bus (the same path `rag load` uses)."""

    async def publish(self, event: DocumentEvent) -> str: ...


class AclEraser(Protocol):
    async def delete_acl(self, tenant_id: TenantId, document_id: DocumentId) -> int:
        """Remove a document's ACL row. Returns the new policy epoch."""
        ...


class DocumentIndexAudit(Protocol):
    """Per-document view of one search index."""

    async def document_versions(
        self, tenant_id: TenantId, document_id: DocumentId
    ) -> dict[int, int]:
        """version -> number of chunks currently stored for this document."""
        ...

    async def delete_versions(
        self, tenant_id: TenantId, document_id: DocumentId, versions: Collection[int]
    ) -> int: ...


class EventPurger(Protocol):
    async def count_document_events(self, tenant_id: TenantId, document_id: DocumentId) -> int: ...

    async def purge_document_events(self, tenant_id: TenantId, document_id: DocumentId) -> int: ...
    

@dataclass(frozen=True, slots=True)
class AuditEntry:
    actor: str
    role: str
    tenant: str | None
    action: str  # "acl.set", "document.purge", "denied:acl.set", ...
    target: str
    detail: dict[str, Any] = field(default_factory=dict)  # never document text
    at: str = ""  # set by the store


class AuditLog(Protocol):
    async def record(self, entry: AuditEntry) -> None: ...

    async def list_entries(
        self, tenant: str | None, limit: int, *, prefixes: tuple[str, ...] | None = None
    ) -> list[AuditEntry]:
        """Newest first. tenant=None means every tenant. `prefixes` keeps only matching actions."""
        ...


class AccountStore(Protocol):
    async def get(self, username: str) -> Account | None: ...

    async def list_accounts(self, tenant: str | None, limit: int) -> list[Account]: ...

    async def create(self, account: Account) -> bool:
        """False if the username is taken."""
        ...

    async def save(self, account: Account) -> None: ...

    async def delete(self, username: str) -> bool: ...

    async def count_active_platform_admins(self) -> int: ...


@dataclass(frozen=True, slots=True)
class BlobInfo:
    version: int
    kind: str  # "original", "text" or "meta"
    size: int


class BlobStore(Protocol):
    """Keeps the originals and extracted text of documents, keyed by tenant, document, version."""

    async def put(self, tenant_id: TenantId, document_id: DocumentId, version: int, kind: str, data: bytes) -> None: ...

    async def get(self, tenant_id: TenantId, document_id: DocumentId, version: int, kind: str) -> bytes | None: ...

    async def list_blobs(self, tenant_id: TenantId, document_id: DocumentId) -> list[BlobInfo]: ...

    async def delete_document(self, tenant_id: TenantId, document_id: DocumentId) -> int:
        """Remove everything stored for the document. Returns how many items were removed."""
        ...

        