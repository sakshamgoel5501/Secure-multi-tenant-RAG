from __future__ import annotations

import asyncio
from collections.abc import Collection
from dataclasses import replace

from domain.models import (
    DocStatus,
    DocumentId,
    DocumentState,
    PromotionOutcome,
    TenantId,
)

_Key = tuple[TenantId, DocumentId]


class InMemoryDocStateStore:
    """Fake DocStateStore. One lock makes every public method atomic, like a DB transaction."""

    def __init__(self) -> None:
        self._states: dict[_Key, DocumentState] = {}
        self._tombstones: dict[_Key, int] = {}  # version at which each doc was deleted
        self._lock = asyncio.Lock()

    # ---- unlocked helpers (callers must hold the lock) ----

    def _seen(self, key: _Key, version: int) -> DocumentState:
        tenant_id, document_id = key
        state = self._states.get(key)
        if state is None:
            state = DocumentState(document_id, tenant_id, version, None, DocStatus.ACTIVE)
        elif version > state.latest_seen_version:
            state = replace(state, latest_seen_version=version)
        self._states[key] = state
        return state

    # ---- DocStateStore port ----

    async def record_seen(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> DocumentState:
        async with self._lock:
            return self._seen((tenant_id, document_id), version)

    async def promote(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> PromotionOutcome:
        key = (tenant_id, document_id)
        async with self._lock:
            state = self._seen(key, version)

            if state.status is DocStatus.DELETED:
                if version <= self._tombstones[key]:
                    return PromotionOutcome.STALE
                self._states[key] = replace(state, active_version=version, status=DocStatus.ACTIVE)
                return PromotionOutcome.PROMOTED

            if state.active_version == version:
                return PromotionOutcome.ALREADY_ACTIVE
            if state.active_version is not None and version < state.active_version:
                return PromotionOutcome.STALE

            self._states[key] = replace(state, active_version=version)
            return PromotionOutcome.PROMOTED

    async def tombstone(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> DocumentState:
        key = (tenant_id, document_id)
        async with self._lock:
            state = self._states.get(key)
            if state is None:
                state = DocumentState(document_id, tenant_id, version, None, DocStatus.DELETED)
            elif version < state.latest_seen_version:
                return state  # a newer event already exists; this delete is outdated
            else:
                state = replace(state, latest_seen_version=version, status=DocStatus.DELETED)
            self._states[key] = state
            self._tombstones[key] = max(version, self._tombstones.get(key, 0))
            return state

    async def get(self, tenant_id: TenantId, document_id: DocumentId) -> DocumentState | None:
        async with self._lock:
            return self._states.get((tenant_id, document_id))
        
    async def get_many(
        self, tenant_id: TenantId, document_ids: Collection[DocumentId]
    ) -> dict[DocumentId, DocumentState]:
        async with self._lock:
            return {
                d: self._states[(tenant_id, d)]
                for d in document_ids
                if (tenant_id, d) in self._states
            }


        