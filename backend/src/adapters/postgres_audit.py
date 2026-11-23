from __future__ import annotations

import json

import asyncpg

from domain.ops_ports import AuditEntry

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id     bigserial PRIMARY KEY,
    at     timestamptz NOT NULL DEFAULT now(),
    actor  text NOT NULL,
    role   text NOT NULL,
    tenant text,
    action text NOT NULL,
    target text NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS audit_log_tenant_idx ON audit_log (tenant, id DESC);
"""


class PostgresAuditLog:
    """Append-only by convention: this class never updates or deletes. In production, also
    REVOKE UPDATE and DELETE on the table from the application's database role."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=3)
        async with self._p().acquire() as conn:
            await conn.execute(SCHEMA)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def reset(self) -> None:
        """Tests only."""
        await self._p().execute("TRUNCATE audit_log")

    def _p(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("call start() first")
        return self._pool

    async def record(self, entry: AuditEntry) -> None:
        await self._p().execute(
            "INSERT INTO audit_log (actor, role, tenant, action, target, detail) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
            entry.actor,
            entry.role,
            entry.tenant,
            entry.action,
            entry.target,
            json.dumps(entry.detail),
        )

    async def list_entries(
        self, tenant: str | None, limit: int, *, prefixes: tuple[str, ...] | None = None
    ) -> list[AuditEntry]:
        rows = await self._p().fetch(
            "SELECT at, actor, role, tenant, action, target, detail FROM audit_log "
            "WHERE ($1::text IS NULL OR tenant = $1) "
            "AND ($3::text[] IS NULL OR EXISTS "
            "(SELECT 1 FROM unnest($3::text[]) AS p WHERE action LIKE p || '%')) "
            "ORDER BY id DESC LIMIT $2",
            tenant,
            limit,
            list(prefixes) if prefixes else None,
        )
        return [
            AuditEntry(
                r["actor"], r["role"], r["tenant"], r["action"], r["target"],
                json.loads(r["detail"]), r["at"].isoformat(),
            )
            for r in rows
        ]  # fmt: skip
    

    