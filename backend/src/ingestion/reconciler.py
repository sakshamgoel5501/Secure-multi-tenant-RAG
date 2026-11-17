from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from domain.models import DocumentId, DocumentState, TenantId
from domain.ops_ports import IndexInspector, StateScanner

log = logging.getLogger("rag.reconciler")

RepairFn = Callable[[TenantId, DocumentId, int], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class Missing:
    tenant_id: TenantId
    document_id: DocumentId
    version: int
    index: str


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    orphans_deleted: int
    missing: tuple[Missing, ...]
    repaired: int


class Reconciler:
    """Compares the commit point (doc_state) with each index and repairs drift.

    Orphans (chunks no query can ever see) are deleted. Missing chunks (an active version with
    no chunks in some index, e.g. after a wiped index) are reported and, if a repair function is
    given, re-indexed from the source of truth.

    Race safety: it must never delete the chunks of a version that is still being ingested,
    because the worker writes chunks first and promotes later. So the newest seen version
    is protected. Orphans of a crashed attempt are removed once a newer version supersedes them.
    It reads each index BEFORE the states, so the state view is at least as new as the index view.
    Repairs are idempotent, so a false "missing" caused by that ordering is harmless.
    """

    def __init__(
        self,
        scanner: StateScanner,
        indexes: Mapping[str, IndexInspector],
        repair: RepairFn | None = None,
    ) -> None:
        self._scanner = scanner
        self._indexes = indexes
        self._repair = repair

    async def run(self) -> ReconcileReport:
        deleted = 0
        missing: list[Missing] = []
        for tenant in await self._scanner.list_tenants():
            snapshots = {name: await idx.list_versions(tenant) for name, idx in self._indexes.items()}
            states = {s.document_id: s for s in await self._scanner.list_states(tenant)}
            for name, present in snapshots.items():
                idx = self._indexes[name]
                for doc, versions in present.items():
                    doomed = versions - self._protected(states.get(doc))
                    if doomed:
                        deleted += await idx.delete_versions(tenant, doc, doomed)
                for doc, s in states.items():
                    v = s.active_version
                    if s.is_searchable and v is not None and v not in present.get(doc, set()):
                        missing.append(Missing(tenant, doc, v, name))

        repaired = 0
        if self._repair is not None:
            seen: set[tuple[TenantId, DocumentId, int]] = set()
            for m in missing:
                key = (m.tenant_id, m.document_id, m.version)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    if await self._repair(*key):
                        repaired += 1
                except Exception:
                    log.exception("repair failed for %s", key)
        return ReconcileReport(deleted, tuple(missing), repaired)

    @staticmethod
    def _protected(s: DocumentState | None) -> set[int]:
        if s is None:
            return set()  # a worker records the version before writing chunks, so no row = orphan
        keep: set[int] = set()
        if s.is_searchable and s.active_version is not None:
            keep.add(s.active_version)
        if s.active_version is None or s.latest_seen_version > s.active_version:
            keep.add(s.latest_seen_version)  # possibly in flight
        return keep
    


    