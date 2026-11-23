from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncpg

from domain.accounts import Account, Role

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    username             text PRIMARY KEY,
    role                 text NOT NULL,
    tenant               text,
    groups               text[] NOT NULL DEFAULT '{}',
    password_hash        text NOT NULL,
    disabled             boolean NOT NULL DEFAULT false,
    must_change_password boolean NOT NULL DEFAULT true,
    token_version        integer NOT NULL DEFAULT 0,
    failed_attempts      integer NOT NULL DEFAULT 0,
    locked_until         double precision NOT NULL DEFAULT 0,
    created_by           text NOT NULL DEFAULT '',
    created_at           timestamptz NOT NULL DEFAULT now(),
    last_login           timestamptz
);
CREATE INDEX IF NOT EXISTS accounts_tenant_idx ON accounts (tenant);
"""

_COLS = (
    "username, role, tenant, groups, password_hash, disabled, must_change_password, "
    "token_version, failed_attempts, locked_until, created_by, created_at, last_login"
)


def _to_account(r: Any) -> Account:
    return Account(
        username=r["username"],
        role=Role(r["role"]),
        tenant=r["tenant"],
        groups=tuple(r["groups"]),
        password_hash=r["password_hash"],
        disabled=r["disabled"],
        must_change_password=r["must_change_password"],
        token_version=r["token_version"],
        failed_attempts=r["failed_attempts"],
        locked_until=r["locked_until"],
        created_by=r["created_by"],
        created_at=r["created_at"].isoformat(),
        last_login=r["last_login"].isoformat() if r["last_login"] else "",
    )


class PostgresAccountStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
        async with self._p().acquire() as conn:
            await conn.execute(SCHEMA)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def reset(self) -> None:
        """Tests only."""
        await self._p().execute("TRUNCATE accounts")

    def _p(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("call start() first")
        return self._pool

    async def get(self, username: str) -> Account | None:
        row = await self._p().fetchrow(f"SELECT {_COLS} FROM accounts WHERE username = $1", username)
        return None if row is None else _to_account(row)

    async def list_accounts(self, tenant: str | None, limit: int) -> list[Account]:
        rows = await self._p().fetch(
            f"SELECT {_COLS} FROM accounts WHERE ($1::text IS NULL OR tenant = $1) "
            "ORDER BY username LIMIT $2",
            tenant,
            limit,
        )
        return [_to_account(r) for r in rows]

    async def create(self, account: Account) -> bool:
        status: str = await self._p().execute(
            "INSERT INTO accounts (username, role, tenant, groups, password_hash, disabled, "
            "must_change_password, token_version, created_by) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) "
            "ON CONFLICT (username) DO NOTHING",
            account.username, account.role.value, account.tenant, list(account.groups),
            account.password_hash, account.disabled, account.must_change_password,
            account.token_version, account.created_by,
        )  # fmt: skip
        return status == "INSERT 0 1"

    async def save(self, a: Account) -> None:
        last = datetime.fromisoformat(a.last_login) if a.last_login else None
        await self._p().execute(
            "UPDATE accounts SET role=$2, tenant=$3, groups=$4, password_hash=$5, disabled=$6, "
            "must_change_password=$7, token_version=$8, failed_attempts=$9, locked_until=$10, "
            "last_login=$11 WHERE username=$1",
            a.username, a.role.value, a.tenant, list(a.groups), a.password_hash, a.disabled,
            a.must_change_password, a.token_version, a.failed_attempts, a.locked_until, last,
        )  # fmt: skip

    async def delete(self, username: str) -> bool:
        status: str = await self._p().execute("DELETE FROM accounts WHERE username = $1", username)
        return status == "DELETE 1"

    async def count_active_platform_admins(self) -> int:
        n: int = await self._p().fetchval(
            "SELECT count(*) FROM accounts WHERE role = 'platform_admin' AND NOT disabled"
        )
        return n
    
    