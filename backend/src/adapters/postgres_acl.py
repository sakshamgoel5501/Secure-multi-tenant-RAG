from __future__ import annotations

from collections.abc import Collection

import asyncpg

from domain.errors import AuthzUnavailable
from domain.models import AclSnapshot, DocumentId, GroupId, TenantId

SCHEMA = """
CREATE TABLE IF NOT EXISTS acl_epoch (
    id    boolean PRIMARY KEY DEFAULT true CHECK (id),
    epoch bigint  NOT NULL
);
INSERT INTO acl_epoch (id, epoch) VALUES (true, 0) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS doc_acl (
    tenant_id   text   NOT NULL,
    document_id text   NOT NULL,
    group_ids   text[] NOT NULL,
    epoch       bigint NOT NULL,
    PRIMARY KEY (tenant_id, document_id)
);
"""

_BUMP = "UPDATE acl_epoch SET epoch = epoch + 1 RETURNING epoch"
_UPSERT = """
INSERT INTO doc_acl (tenant_id, document_id, group_ids, epoch) VALUES ($1, $2, $3, $4)
ON CONFLICT (tenant_id, document_id)
DO UPDATE SET group_ids = EXCLUDED.group_ids, epoch = EXCLUDED.epoch
"""
_READ = """
SELECT document_id, group_ids FROM doc_acl
WHERE tenant_id = $1 AND document_id = ANY($2::text[])
"""
_LIST = "SELECT document_id, group_ids FROM doc_acl WHERE tenant_id = $1"

_DB_ERRORS = (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError)


class PostgresAclStore:
    """Authoritative ACL store AND query-path reader (implements AclReader).

    Every write bumps a single global epoch row inside the same transaction as the ACL change.
    The row lock serializes writers, so commit order == epoch order. The epoch returned by
    set_acl() is the revocation linearization point.

    A reader sees the epoch and the ACL rows from ONE snapshot (REPEATABLE READ), so it can
    never pair a new epoch with old ACLs. Reading from the primary means the reader can't lag;
    with a read replica, the `epoch < min_epoch` check below is what rejects a lagging one.
    Trade-off: all ACL writes serialize on one row. Fine for ACL change rates, and the answer to
    "what if that becomes a bottleneck" is batching writes or a Zanzibar-style store (SpiceDB).
    """

    def __init__(self, dsn: str, *, max_pool_size: int = 10) -> None:
        self._dsn = dsn
        self._max = max_pool_size
        self._pool: asyncpg.Pool | None = None

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=self._max)
        async with self._p().acquire() as conn:
            await conn.execute(SCHEMA)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def reset(self) -> None:
        """Tests only."""
        async with self._p().acquire() as conn, conn.transaction():
            await conn.execute("TRUNCATE doc_acl")
            await conn.execute("UPDATE acl_epoch SET epoch = 0")

    def _p(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("call start() first")
        return self._pool

    async def set_acl(
        self, tenant_id: TenantId, document_id: DocumentId, groups: Collection[GroupId]
    ) -> int:
        async with self._p().acquire() as conn, conn.transaction():
            epoch: int = await conn.fetchval(_BUMP)
            await conn.execute(_UPSERT, tenant_id, document_id, sorted(groups), epoch)
        return epoch

    async def current_epoch(self) -> int:
        """What the auth layer should stamp on a request at request start."""
        try:
            epoch: int = await self._p().fetchval("SELECT epoch FROM acl_epoch")
        except _DB_ERRORS as exc:
            raise AuthzUnavailable(f"ACL store unavailable: {exc}") from exc
        return epoch

    async def list_acls(self, tenant_id: TenantId) -> dict[DocumentId, frozenset[GroupId]]:
        """Admin read of every ACL in one tenant (not used on the query path)."""
        rows = await self._p().fetch(_LIST, tenant_id)
        return {
            DocumentId(r["document_id"]): frozenset(GroupId(g) for g in r["group_ids"])
            for r in rows
        }

    async def acls_for(
        self,
        tenant_id: TenantId,
        document_ids: Collection[DocumentId],
        *,
        min_epoch: int,
    ) -> AclSnapshot:
        try:
            async with (
                self._p().acquire() as conn,
                conn.transaction(isolation="repeatable_read", readonly=True),
            ):
                epoch: int = await conn.fetchval("SELECT epoch FROM acl_epoch")
                rows = await conn.fetch(_READ, tenant_id, list(document_ids))
        except _DB_ERRORS as exc:
            raise AuthzUnavailable(f"ACL store unavailable: {exc}") from exc
        if epoch < min_epoch:
            raise AuthzUnavailable(f"ACL state at epoch {epoch}, need {min_epoch}")
        return AclSnapshot(
            epoch,
            {
                DocumentId(r["document_id"]): frozenset(GroupId(g) for g in r["group_ids"])
                for r in rows
            },
        )
    
    async def delete_acl(self, tenant_id: TenantId, document_id: DocumentId) -> int:
        """Erase a document's ACL. Bumps the epoch in the same transaction, like any ACL change."""
        async with self._p().acquire() as conn, conn.transaction():
            epoch: int = await conn.fetchval(_BUMP)
            await conn.execute(
                "DELETE FROM doc_acl WHERE tenant_id = $1 AND document_id = $2",
                tenant_id,
                document_id,
            )
        return epoch
    
    