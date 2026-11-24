"""
The compare-and-set from earlier, now real. The CHECK constraint enforces active <= latest_seen in the 
database itself.
"""

from __future__ import annotations

from collections.abc import Collection

import asyncpg

from domain.models import (
    DocStatus,
    DocumentId,
    DocumentState,
    PromotionOutcome,
    TenantId,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS doc_state (
    tenant_id           text   NOT NULL,
    document_id         text   NOT NULL,
    latest_seen_version bigint NOT NULL,
    active_version      bigint,
    deleted_version     bigint,
    PRIMARY KEY (tenant_id, document_id),
    CHECK (active_version IS NULL OR active_version <= latest_seen_version)
);
ALTER TABLE doc_state ADD COLUMN IF NOT EXISTS purged boolean NOT NULL DEFAULT false;
"""

_COLS = "tenant_id, document_id, latest_seen_version, active_version, deleted_version, purged"
_INSERT_COLS = "tenant_id, document_id, latest_seen_version, active_version, deleted_version"

_UPSERT_SEEN = f"""
INSERT INTO doc_state ({_INSERT_COLS}) VALUES ($1, $2, $3, NULL, NULL)
ON CONFLICT (tenant_id, document_id) DO UPDATE
SET latest_seen_version = GREATEST(doc_state.latest_seen_version, EXCLUDED.latest_seen_version)
RETURNING {_COLS}
"""

# The compare-and-set. Zero rows updated means we lost (stale) or it was a duplicate.
_CAS = """
UPDATE doc_state SET active_version = $3, purged = false
WHERE tenant_id = $1 AND document_id = $2
  AND (active_version IS NULL OR active_version < $3)
  AND (deleted_version IS NULL OR deleted_version < $3)
"""

_TOMBSTONE = f"""
INSERT INTO doc_state ({_INSERT_COLS}) VALUES ($1, $2, $3, NULL, $3)
ON CONFLICT (tenant_id, document_id) DO UPDATE
SET latest_seen_version = EXCLUDED.latest_seen_version,
    deleted_version = GREATEST(COALESCE(doc_state.deleted_version, 0), EXCLUDED.deleted_version)
WHERE EXCLUDED.latest_seen_version >= doc_state.latest_seen_version
RETURNING {_COLS}
"""

_SELECT = f"SELECT {_COLS} FROM doc_state WHERE tenant_id = $1 AND document_id = $2"
_SELECT_MANY = (
    f"SELECT {_COLS} FROM doc_state WHERE tenant_id = $1 AND document_id = ANY($2::text[])"
)


def _to_state(row: asyncpg.Record) -> DocumentState:
    active: int | None = row["active_version"]
    deleted: int | None = row["deleted_version"]
    # Deleted means a tombstone exists that no later activation has superseded.
    is_deleted = deleted is not None and (active is None or active <= deleted)
    return DocumentState(
        document_id=DocumentId(row["document_id"]),
        tenant_id=TenantId(row["tenant_id"]),
        latest_seen_version=row["latest_seen_version"],
        active_version=active,
        status=DocStatus.DELETED if is_deleted else DocStatus.ACTIVE,
        purged=bool(row["purged"]),
    )


class PostgresDocStateStore:
    """DocStateStore on Postgres. Atomicity comes from row locks, not Python locks."""

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
        await self._p().execute("TRUNCATE doc_state")

    def _p(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("call start() first")
        return self._pool

    async def record_seen(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> DocumentState:
        row = await self._p().fetchrow(_UPSERT_SEEN, tenant_id, document_id, version)
        if row is None:
            raise RuntimeError("upsert returned no row")
        return _to_state(row)

    async def promote(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> PromotionOutcome:
        async with self._p().acquire() as conn, conn.transaction():
            await conn.execute(_UPSERT_SEEN, tenant_id, document_id, version)
            status: str = await conn.execute(_CAS, tenant_id, document_id, version)
            if status == "UPDATE 1":
                return PromotionOutcome.PROMOTED
            row = await conn.fetchrow(_SELECT, tenant_id, document_id)
        if row is None:
            raise RuntimeError("row vanished after upsert")
        deleted: int | None = row["deleted_version"]
        active: int | None = row["active_version"]
        if deleted is not None and version <= deleted:
            return PromotionOutcome.STALE
        if active == version:
            return PromotionOutcome.ALREADY_ACTIVE
        return PromotionOutcome.STALE

    async def tombstone(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> DocumentState:
        row = await self._p().fetchrow(_TOMBSTONE, tenant_id, document_id, version)
        if row is not None:
            return _to_state(row)
        # The WHERE clause rejected an outdated delete: return the unchanged state.
        current = await self.get(tenant_id, document_id)
        if current is None:
            raise RuntimeError("row vanished during tombstone")
        return current

    async def get(self, tenant_id: TenantId, document_id: DocumentId) -> DocumentState | None:
        row = await self._p().fetchrow(_SELECT, tenant_id, document_id)
        return None if row is None else _to_state(row)

    async def get_many(
        self, tenant_id: TenantId, document_ids: Collection[DocumentId]
    ) -> dict[DocumentId, DocumentState]:
        rows = await self._p().fetch(_SELECT_MANY, tenant_id, list(document_ids))
        states = [_to_state(r) for r in rows]
        return {s.document_id: s for s in states}
    
    async def mark_purged(self, tenant_id: TenantId, document_id: DocumentId) -> None:
        await self._p().execute(
            "UPDATE doc_state SET purged = true WHERE tenant_id = $1 AND document_id = $2",
            tenant_id, document_id,
        )  # fmt: skip



