from dataclasses import replace
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI

from account_helpers import make_account
from adapters.memory_accounts import InMemoryAccountStore
from adapters.memory_audit import InMemoryAuditLog
from domain.accounts import Account, Role
from domain.models import SecurityContext
from serving.admin_auth import Principal, admin_identity
from serving.auth import jwt_identity
from serving.auth_service import AuthService

U, A = "u" * 32, "a" * 32


class Epochs:
    async def current_epoch(self) -> int:
        return 5


async def build(*accounts: Account) -> tuple[httpx.AsyncClient, InMemoryAccountStore, AuthService]:
    store = InMemoryAccountStore()
    for a in accounts:
        await store.create(a)
    service = AuthService(store, InMemoryAuditLog(), U, A)
    user_dep = jwt_identity(U, Epochs(), accounts=store)
    admin_dep = admin_identity(A, store)
    app = FastAPI()

    @app.get("/who")
    async def who(ctx: Annotated[SecurityContext, Depends(user_dep)]) -> dict[str, object]:
        return {"tenant": ctx.tenant_id, "groups": sorted(ctx.group_ids), "epoch": ctx.policy_epoch}

    @app.get("/admin-who")
    async def admin_who(p: Annotated[Principal, Depends(admin_dep)]) -> dict[str, object]:
        return {"actor": p.actor, "role": p.role, "tenant": p.tenant, "group": p.group}

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, store, service


def bearer(service: AuthService, account: Account) -> dict[str, str]:
    return {"Authorization": f"Bearer {service.issue(account)}"}


async def test_groups_come_from_the_account_not_the_token() -> None:
    alice = make_account("alice")
    client, store, service = await build(alice)
    headers = bearer(service, alice)
    first = (await client.get("/who", headers=headers)).json()
    assert first["groups"] == ["eng"] and first["epoch"] == 5
    await store.save(replace(alice, groups=("hr",)))
    assert (await client.get("/who", headers=headers)).json()["groups"] == ["hr"]


async def test_disabled_and_stale_sessions_are_refused() -> None:
    alice = make_account("alice")
    client, store, service = await build(alice)
    headers = bearer(service, alice)
    await store.save(replace(alice, disabled=True))
    assert (await client.get("/who", headers=headers)).status_code == 401
    await store.save(replace(alice, token_version=1))
    assert (await client.get("/who", headers=headers)).status_code == 401


async def test_a_pending_password_change_blocks_use() -> None:
    bob = make_account("bob", must_change=True)
    client, _, service = await build(bob)
    assert (await client.get("/who", headers=bearer(service, bob))).status_code == 403


async def test_user_and_admin_tokens_do_not_cross() -> None:
    alice, root = make_account("alice"), make_account("root", Role.PLATFORM_ADMIN, None, ())
    client, _, service = await build(alice, root)
    assert (await client.get("/who", headers=bearer(service, root))).status_code == 401
    assert (await client.get("/admin-who", headers=bearer(service, alice))).status_code == 401


async def test_admin_identity_reflects_the_stored_account() -> None:
    boss = make_account("boss", Role.TENANT_ADMIN, "t1", ())
    gwen = make_account("gwen", Role.GROUP_ADMIN, "t1", ("hr",))
    client, _, service = await build(boss, gwen)
    assert (await client.get("/admin-who", headers=bearer(service, boss))).json()["role"] == "tenant_admin"
    assert (await client.get("/admin-who", headers=bearer(service, gwen))).json()["group"] == "hr"

    