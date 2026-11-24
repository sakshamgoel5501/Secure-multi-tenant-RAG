import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from domain.accounts import (
    USERNAME,
    Account,
    Role,
    account_json,
    check_new_password,
    generate_password,
    hash_password,
    validate_membership,
)
from domain.ops_ports import AccountStore, AuditEntry, AuditLog
from serving.admin_auth import Principal, admin_identity

log = logging.getLogger("rag.admin.users")
TENANT_MANAGED = frozenset({Role.USER, Role.GROUP_ADMIN})


class NewAccount(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    role: Literal["user", "group_admin", "tenant_admin", "platform_admin"]
    tenant: str | None = Field(default=None, max_length=32)
    groups: list[str] = Field(default_factory=list, max_length=20)
    password: str | None = Field(default=None, max_length=128)  # omitted: one is generated


class AccountPatch(BaseModel):
    disabled: bool | None = None
    groups: list[str] | None = Field(default=None, max_length=20)


def create_users_router(accounts: AccountStore, audit: AuditLog, *, admin_key: str) -> APIRouter:
    """Platform administrators manage every account. Tenant administrators manage users and group
    administrators of their own tenant. Passwords are never logged or audited."""
    who = Depends(admin_identity(admin_key, accounts))
    router = APIRouter(prefix="/admin/users")

    def may_manage(p: Principal, tenant: str | None, role: Role) -> bool:
        if p.platform:
            return True
        return p.role == "tenant_admin" and tenant is not None and tenant == p.tenant and role in TENANT_MANAGED

    async def denial(p: Principal, action: str, target: str, tenant: str | None) -> HTTPException:
        try:
            await audit.record(AuditEntry(p.actor, p.role, tenant, f"denied:{action}", target))
        except Exception:
            log.exception("audit write failed while recording a denial")
        return HTTPException(status_code=403, detail="outside your admin scope")

    async def record(
        p: Principal, tenant: str | None, action: str, target: str, detail: dict[str, Any]
    ) -> None:
        """No audit, no action."""
        try:
            await audit.record(AuditEntry(p.actor, p.role, tenant, action, target, detail))
        except Exception as exc:
            log.warning("audit write failed: %r", exc)
            raise HTTPException(status_code=503, detail="audit log unavailable; no change was made") from exc

    async def target(p: Principal, username: str, action: str) -> Account:
        account = await accounts.get(username.strip().lower())
        if account is None:
            if p.platform:
                raise HTTPException(status_code=404, detail="unknown account")
            raise await denial(p, action, username, p.tenant)  # same answer as "not yours"
        if not may_manage(p, account.tenant, account.role):
            raise await denial(p, action, account.username, account.tenant)
        return account

    @router.get("")
    async def list_accounts(
        tenant: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
        p: Principal = who,
    ) -> dict[str, Any]:
        if p.platform:
            scope = tenant
        elif p.role == "tenant_admin" and tenant in (None, p.tenant):
            scope = p.tenant
        else:
            raise await denial(p, "user.list", "", tenant or p.tenant)
        return {"accounts": [account_json(a) for a in await accounts.list_accounts(scope, limit)]}

    @router.post("", status_code=201)
    async def create(body: NewAccount, p: Principal = who) -> dict[str, Any]:
        username = body.username.strip().lower()
        role, tenant = Role(body.role), body.tenant or None
        if not may_manage(p, tenant, role):
            raise await denial(p, "user.create", username, tenant)
        if not USERNAME.match(username):
            raise HTTPException(
                status_code=422,
                detail="usernames are 3-32 characters: lowercase letters, digits, dot, dash, underscore",
            )
        groups = tuple(sorted(set(body.groups)))
        try:
            validate_membership(role, tenant, groups)
            if body.password is not None:
                check_new_password(body.password, username)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if await accounts.get(username) is not None:
            raise HTTPException(status_code=409, detail="that username is taken")

        generated = body.password is None
        password = generate_password() if body.password is None else body.password
        await record(p, tenant, "user.create", username, {"role": role.value, "groups": list(groups)})
        account = Account(
            username, role, tenant, groups,
            await asyncio.to_thread(hash_password, password),
            must_change_password=True,
            created_by=p.actor,
            created_at=datetime.now(UTC).isoformat(),
        )  # fmt: skip
        if not await accounts.create(account):
            raise HTTPException(status_code=409, detail="that username is taken")
        out: dict[str, Any] = {"account": account_json(account)}
        if generated:
            out["temporary_password"] = password  # shown once, never stored in clear
        return out

    @router.patch("/{username}")
    async def update(username: str, body: AccountPatch, p: Principal = who) -> dict[str, Any]:
        account = await target(p, username, "user.update")
        if body.disabled and account.username == p.actor:
            raise HTTPException(status_code=400, detail="you can't disable your own account")
        groups = account.groups if body.groups is None else tuple(sorted(set(body.groups)))
        try:
            validate_membership(account.role, account.tenant, groups)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        updated = replace(
            account,
            groups=groups,
            disabled=account.disabled if body.disabled is None else body.disabled,
        )
        await record(
            p, account.tenant, "user.update", account.username,
            {"disabled": updated.disabled, "groups": list(groups)},
        )  # fmt: skip
        await accounts.save(updated)
        return {"account": account_json(updated)}

    @router.post("/{username}/reset-password")
    async def reset_password(username: str, p: Principal = who) -> dict[str, Any]:
        account = await target(p, username, "user.reset_password")
        if account.username == p.actor:
            raise HTTPException(status_code=400, detail="change your own password from the Account page")
        temporary = generate_password()
        await record(p, account.tenant, "user.reset_password", account.username, {})
        await accounts.save(
            replace(
                account,
                password_hash=await asyncio.to_thread(hash_password, temporary),
                must_change_password=True,
                token_version=account.token_version + 1,  # ends every existing session
                failed_attempts=0,
                locked_until=0.0,
            )
        )
        return {"temporary_password": temporary}

    @router.delete("/{username}")
    async def delete(username: str, p: Principal = who) -> dict[str, str]:
        account = await target(p, username, "user.delete")
        if account.username == p.actor:
            raise HTTPException(status_code=400, detail="you can't delete your own account")
        await record(p, account.tenant, "user.delete", account.username, {"role": account.role.value})
        await accounts.delete(account.username)
        return {"deleted": account.username}

    return router


