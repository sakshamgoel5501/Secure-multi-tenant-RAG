from __future__ import annotations

from collections.abc import Collection

from domain.errors import AuthzUnavailable
from domain.models import AclSnapshot, DocumentId, GroupId, TenantId

_Key = tuple[TenantId, DocumentId]


class InMemoryAclPrimary:
    """Authoritative ACL store. Every write bumps a global epoch and returns it."""

    def __init__(self) -> None:
        self._epoch = 0
        self._acls: dict[_Key, frozenset[GroupId]] = {}

    def set_acl(
        self, tenant_id: TenantId, document_id: DocumentId, groups: Collection[GroupId]
    ) -> int:
        self._epoch += 1
        self._acls[(tenant_id, document_id)] = frozenset(groups)
        return self._epoch  # the caller now holds the revocation linearization point

    def export_state(self) -> tuple[int, dict[_Key, frozenset[GroupId]]]:
        return self._epoch, dict(self._acls)


class InMemoryAclReplica:
    """Local read replica that lags the primary until sync() is called."""

    def __init__(self, primary: InMemoryAclPrimary) -> None:
        self._primary = primary
        self._epoch = 0
        self._acls: dict[_Key, frozenset[GroupId]] = {}
        self.up = True  # tests flip this to simulate an outage

    def sync(self) -> None:
        self._epoch, self._acls = self._primary.export_state()

    async def acls_for(
        self,
        tenant_id: TenantId,
        document_ids: Collection[DocumentId],
        *,
        min_epoch: int,
    ) -> AclSnapshot:
        if not self.up:
            raise AuthzUnavailable("ACL replica is down")
        if self._epoch < min_epoch:
            raise AuthzUnavailable(f"ACL replica at epoch {self._epoch}, need {min_epoch}")
        return AclSnapshot(
            self._epoch,
            {
                d: self._acls[(tenant_id, d)]
                for d in document_ids
                if (tenant_id, d) in self._acls
            },
        )
    



