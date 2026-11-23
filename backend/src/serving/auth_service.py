from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

import jwt

from domain.accounts import (
    ADMIN_ROLES,
    Account,
    Role,
    check_new_password,
    dummy_hash,
    hash_password,
    verify_password,
)
from domain.ops_ports import AccountStore, AuditEntry, AuditLog

log = logging.getLogger("rag.auth")


class AdminDisabled(Exception):
    """The account is an administrator, but this server runs without the admin API."""


class AuthService:
    def __init__(
        self,
        accounts: AccountStore,
        audit: AuditLog,
        user_secret: str,
        admin_secret: str | None,
        *,
        ttl: int = 8 * 3600,
        max_failures: int = 5,
        lock_seconds: int = 900,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._accounts = accounts
        self._audit = audit
        self._user_secret = user_secret
        self._admin_secret = admin_secret
        self._ttl = ttl
        self._max_failures = max_failures
        self._lock_seconds = lock_seconds
        self._clock = clock

    @property
    def ttl(self) -> int:
        return self._ttl

    def issue(self, account: Account) -> str:
        now = int(self._clock())
        claims: dict[str, object] = {
            "sub": account.username, "iat": now, "exp": now + self._ttl, "tv": account.token_version,
        }  # fmt: skip
        if account.role is Role.USER:
            claims |= {"aud": "rag", "tenant": account.tenant, "groups": list(account.groups)}
            return jwt.encode(claims, self._user_secret, algorithm="HS256")
        if self._admin_secret is None:
            raise AdminDisabled
        claims |= {"aud": "rag-admin", "role": account.role.value}
        if account.tenant:
            claims["tenant"] = account.tenant
        if account.role is Role.GROUP_ADMIN:
            claims["group"] = account.groups[0]
        return jwt.encode(claims, self._admin_secret, algorithm="HS256")

    async def login(self, username: str, password: str) -> tuple[Account, str] | None:
        """None for every kind of failure, so a caller can't tell a wrong password from an unknown
        name, a locked account or a disabled one."""
        now = self._clock()
        account = await self._accounts.get(username.strip().lower())
        if account is None:
            await asyncio.to_thread(verify_password, password, dummy_hash())
            return None
        ok = await asyncio.to_thread(verify_password, password, account.password_hash)
        locked = account.locked_until > now
        if locked or account.disabled or not ok:
            if not ok and not locked and not account.disabled:
                failures = account.failed_attempts + 1
                lock = failures >= self._max_failures
                account = replace(
                    account,
                    failed_attempts=0 if lock else failures,
                    locked_until=now + self._lock_seconds if lock else 0.0,
                )
                await self._accounts.save(account)
            await self._note(account, "auth.login_failed")
            return None
        if account.role in ADMIN_ROLES and self._admin_secret is None:
            raise AdminDisabled
        account = replace(
            account,
            failed_attempts=0,
            locked_until=0.0,
            last_login=datetime.fromtimestamp(now, UTC).isoformat(),
        )
        await self._accounts.save(account)
        await self._note(account, "auth.login")
        return account, self.issue(account)

    async def resolve(self, token: str) -> Account | None:
        """The live account behind a session token, or None. Used by /auth/me and /auth/password,
        which must work even while a password change is pending."""
        for secret, audience in ((self._user_secret, "rag"), (self._admin_secret, "rag-admin")):
            if not secret:
                continue
            try:
                claims = jwt.decode(
                    token, secret, algorithms=["HS256"], audience=audience,
                    options={"require": ["exp", "sub"]},
                )  # fmt: skip
            except jwt.InvalidTokenError:
                continue
            account = await self._accounts.get(str(claims["sub"]))
            if account is None or account.disabled or claims.get("tv") != account.token_version:
                return None
            return account if (audience == "rag") == (account.role is Role.USER) else None
        return None

    async def change_password(self, account: Account, current: str, new: str) -> Account:
        if not await asyncio.to_thread(verify_password, current, account.password_hash):
            raise ValueError("the current password is incorrect")
        check_new_password(new, account.username)
        if new == current:
            raise ValueError("choose a different password")
        updated = replace(
            account,
            password_hash=await asyncio.to_thread(hash_password, new),
            must_change_password=False,
            token_version=account.token_version + 1,
            failed_attempts=0,
            locked_until=0.0,
        )
        await self._accounts.save(updated)
        await self._note(updated, "user.password_change")
        return updated

    async def _note(self, account: Account, action: str) -> None:
        try:
            await self._audit.record(
                AuditEntry(account.username, account.role.value, account.tenant, action, account.username)
            )
        except Exception:  # noqa: BLE001
            log.warning("audit write failed for %s", action, exc_info=True)

            