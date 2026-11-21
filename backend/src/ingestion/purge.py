from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from domain.models import DocumentId, TenantId
from domain.ops_ports import AclAdmin, AclEraser, DocumentIndexAudit, EventPurger
from domain.ports import DocStateStore


class AclStore(AclAdmin, AclEraser, Protocol): ...


@dataclass(frozen=True, slots=True)
class Footprint:
    status: str | None  # the state row: kept after a purge, but holds no content
    has_acl: bool
    chunks: dict[str, dict[int, int]]  # index name -> version -> chunk count
    events: int  # stream and dead-letter entries that still carry the text

    @property
    def content_left(self) -> bool:
        return self.has_acl or self.events > 0 or any(self.chunks.values())


@dataclass(frozen=True, slots=True)
class PurgeReport:
    chunks_deleted: dict[str, int]
    events_deleted: int
    acl_removed: bool
    epoch: int | None
    after: Footprint


class Purger:
    """Erases every stored trace of a document's content.

    It keeps one content-free tombstone (ids and a version number) in the state table. Without
    it, a late or replayed old event could resurrect the document. Order matters: tombstone
    first, so the document is invisible at once; then the ACL; then a sweep of events and chunks.
    The sweep runs twice to catch a worker that was mid-write. A worker that is still running when
    the second sweep ends could leave orphan chunks, which the reconciler removes because the
    document is tombstoned. The footprint shows them if so.
    """

    def __init__(
        self,
        states: DocStateStore,
        acls: AclStore,
        indexes: Mapping[str, DocumentIndexAudit],
        events: EventPurger,
    ) -> None:
        self._states = states
        self._acls = acls
        self._indexes = indexes
        self._events = events

    async def footprint(self, tenant: TenantId, doc: DocumentId) -> Footprint:
        state = await self._states.get(tenant, doc)
        return Footprint(
            status=state.status.value if state else None,
            has_acl=doc in await self._acls.list_acls(tenant),
            chunks={
                name: await idx.document_versions(tenant, doc)
                for name, idx in self._indexes.items()
            },
            events=await self._events.count_document_events(tenant, doc),
        )

    async def purge(self, tenant: TenantId, doc: DocumentId) -> PurgeReport:
        state = await self._states.get(tenant, doc)
        if state is None:
            raise KeyError(doc)
        await self._states.tombstone(tenant, doc, state.latest_seen_version + 1)

        had_acl = doc in await self._acls.list_acls(tenant)
        epoch = await self._acls.delete_acl(tenant, doc) if had_acl else None

        deleted = dict.fromkeys(self._indexes, 0)
        events = 0
        for _ in range(2):
            events += await self._events.purge_document_events(tenant, doc)
            for name, idx in self._indexes.items():
                versions = await idx.document_versions(tenant, doc)
                if versions:
                    deleted[name] += await idx.delete_versions(tenant, doc, set(versions))
        return PurgeReport(deleted, events, had_acl, epoch, await self.footprint(tenant, doc))
    


    