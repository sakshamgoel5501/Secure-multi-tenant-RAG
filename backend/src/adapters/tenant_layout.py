from __future__ import annotations

import hashlib
from collections.abc import Collection

from adapters.qdrant_stores import _slug


class TenantLayout:
    """Which Qdrant collection holds a tenant's chunks. Pooled tenants share the `rag` collections.
    A silo tenant gets its own, named from the tenant plus a short hash so that two ids that slug
    to the same text still get different collections."""

    def __init__(self, model_version: str, silo_tenants: Collection[str] = ()) -> None:
        self._version = model_version
        self._silo = frozenset(silo_tenants)

    def is_silo(self, tenant: str) -> bool:
        return tenant in self._silo

    def prefix(self, tenant: str) -> str:
        if tenant not in self._silo:
            return "rag"
        digest = hashlib.sha256(tenant.encode()).hexdigest()[:6]
        return f"rag_t_{_slug(tenant)}_{digest}"

    def dense_collection(self, tenant: str) -> str:
        return f"{self.prefix(tenant)}_dense_{_slug(self._version)}"

    def lexical_collection(self, tenant: str) -> str:
        return f"{self.prefix(tenant)}_lexical"
    
    