from dataclasses import dataclass
from typing import Any

import httpx
from account_helpers import PASSWORD, make_account
from fastapi import FastAPI

from adapters.memory_accounts import InMemoryAccountStore
from adapters.memory_audit import InMemoryAuditLog
from domain.accounts import Role
from serving.admin_users import create_users_router
from serving.auth_service import AuthService

U, A = "u" * 32, "a" * 32
STRONG = "a much longer password"


@dataclass
class Env:
    client: httpx.AsyncClient
    store: InMemoryAccountStore
    audit: InMemoryAuditLog
    service: AuthService
    root: dict[str, str]
    boss: dict[str, str]


async def build() -> Env:
    store, audit = InMemoryAccountStore(), InMemoryAuditLog()
    root = make_account("root", Role.PLATFORM_ADMIN, None, ())
    boss = make_account("boss", Role.TENANT_ADMIN, "t1", ())
    await store.create(root)
    await store.create(boss)
    service = AuthService(store, audit, U, A)
    app = FastAPI()
    app.include_router(create_users_router(store, audit, admin_key=A))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return Env(
        client, store, audit, service,
        {"Authorization": f"Bearer {service.issue(root)}"},
        {"Authorization": f"Bearer {service.issue(boss)}"},
    )  # fmt: skip


async def make_user(env: Env, **extra: Any) -> httpx.Response:
    body = {"username": "bob", "role": "user", "tenant": "t1", "groups": ["eng"], **extra}
    return await env.client.post("/admin/users", json=body, headers=env.root)


async def test_only_platform_administrators_manage_accounts() -> None:
    env = await build()
    assert (await env.client.get("/admin/users", headers=env.boss)).status_code == 403
    assert env.audit.entries[-1].action == "denied:user.list"
    assert (await env.client.get("/admin/users")).status_code == 401


async def test_create_generates_a_one_time_password_that_must_be_changed() -> None:
    env = await build()
    r = await make_user(env)
    assert r.status_code == 201
    temp = r.json()["temporary_password"]
    account = await env.store.get("bob")
    assert account is not None and account.must_change_password and account.created_by == "root"
    assert await env.service.login("bob", temp) is not None
    entry = next(e for e in env.audit.entries if e.action == "user.create")
    assert entry.detail == {"role": "user", "groups": ["eng"]}
    assert temp not in str([e.detail for e in env.audit.entries])


async def test_a_chosen_password_is_checked_and_never_echoed() -> None:
    env = await build()
    assert (await make_user(env, password="short")).status_code == 422
    r = await make_user(env, password=STRONG)
    assert r.status_code == 201 and "temporary_password" not in r.json()
    assert await env.service.login("bob", STRONG) is not None


async def test_bad_shapes_and_duplicates_are_refused() -> None:
    env = await build()
    assert (await make_user(env, role="platform_admin")).status_code == 422  # a tenant was given
    assert (await make_user(env, groups=[])).status_code == 422
    assert (await make_user(env, username="Bad Name")).status_code == 422
    assert (await make_user(env, username="root")).status_code == 409
    assert (await make_user(env, role="group_admin", groups=["eng", "hr"])).status_code == 422


async def test_disabling_blocks_sign_in_but_not_your_own_account() -> None:
    env = await build()
    await make_user(env, password=STRONG)
    r = await env.client.patch("/admin/users/bob", json={"disabled": True}, headers=env.root)
    assert r.status_code == 200 and await env.service.login("bob", STRONG) is None
    own = await env.client.patch("/admin/users/root", json={"disabled": True}, headers=env.root)
    assert own.status_code == 400


async def test_group_changes_are_validated() -> None:
    env = await build()
    await make_user(env, username="gwen", role="group_admin", groups=["hr"])
    bad = await env.client.patch("/admin/users/gwen", json={"groups": ["hr", "eng"]}, headers=env.root)
    assert bad.status_code == 422
    await make_user(env)
    ok = await env.client.patch("/admin/users/bob", json={"groups": ["fin"]}, headers=env.root)
    assert ok.status_code == 200 and ok.json()["account"]["groups"] == ["fin"]


async def test_reset_password_ends_sessions_and_forces_a_change() -> None:
    env = await build()
    await make_user(env, password=STRONG)
    signed_in = await env.service.login("bob", STRONG)
    assert signed_in is not None
    r = await env.client.post("/admin/users/bob/reset-password", headers=env.root)
    assert r.status_code == 200
    assert await env.service.resolve(signed_in[1]) is None
    account = await env.store.get("bob")
    assert account is not None and account.must_change_password
    assert (await env.client.post("/admin/users/root/reset-password", headers=env.root)).status_code == 400


async def test_delete_and_listing() -> None:
    env = await build()
    await make_user(env)
    listing = await env.client.get("/admin/users", params={"tenant": "t1"}, headers=env.root)
    assert {a["username"] for a in listing.json()["accounts"]} == {"boss", "bob"}
    assert "password_hash" not in listing.text
    assert (await env.client.delete("/admin/users/bob", headers=env.root)).status_code == 200
    assert (await env.client.delete("/admin/users/bob", headers=env.root)).status_code == 404
    assert (await env.client.delete("/admin/users/root", headers=env.root)).status_code == 400
    assert PASSWORD not in str([e.detail for e in env.audit.entries])

    