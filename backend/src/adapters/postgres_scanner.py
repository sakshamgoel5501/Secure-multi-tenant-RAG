from __future__ import annotations

import asyncpg

from adapters.postgres_doc_state import _COLS, _to_state
from domain.models import DocumentState, TenantId


class PostgresStateScanner:
    """Read-only enumeration of doc_state for background jobs. It has its own small pool so a
    long scan can't starve the query path. At real scale, page with keyset pagination
    (WHERE document_id > $last ORDER BY document_id LIMIT n) instead of loading a whole tenant."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=2)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _p(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("call start() first")
        return self._pool

    async def list_tenants(self) -> list[TenantId]:
        rows = await self._p().fetch("SELECT DISTINCT tenant_id FROM doc_state ORDER BY tenant_id")
        return [TenantId(r["tenant_id"]) for r in rows]

    async def list_states(self, tenant_id: TenantId) -> list[DocumentState]:
        rows = await self._p().fetch(
            f"SELECT {_COLS} FROM doc_state WHERE tenant_id = $1 ORDER BY document_id", tenant_id
        )
        return [_to_state(r) for r in rows]
    

    