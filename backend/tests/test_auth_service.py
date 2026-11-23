from dataclasses import replace
import jwt
import pytest
import time

from account_helpers import PASSWORD, make_account
from adapters.memory_accounts import InMemoryAccountStore
from adapters.memory_audit import InMemoryAuditLog
from domain.accounts import Account, Role
from serving.auth_service import AdminDisabled, AuthService

USER_SECRET = "u" * 32
ADMIN_SECRET = "a" * 32


class Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now


async def build(
    *accounts: Account, admin_secret: str | None = ADMIN_SECRET
) -> tuple[AuthService, InMemoryAccountStore, InMemoryAuditLog, Clock]:
    store, audit, clock = InMemoryAccountStore(), InMemoryAuditLog(), Clock()
    for a in accounts:
        await store.create(a)
    return AuthService(store, audit, USER_SECRET, admin_secret, clock=clock), store, audit, clock


async def test_login_issues_a_user_token_and_audits_it() -> None:
    svc, _, audit, _ = await build(make_account("alice"))
    result = await svc.login(" ALICE ", PASSWORD)
    assert result is not None
    _, token = result
    claims = jwt.decode(token, USER_SECRET, algorithms=["HS256"], audience="rag")
    assert (claims["sub"], claims["tenant"], claims["groups"]) == ("alice", "t1", ["eng"])
    assert audit.entries[-1].action == "auth.login"


async def test_every_failure_looks_the_same_and_unknown_names_are_not_recorded() -> None:
    svc, _, audit, _ = await build(make_account("alice"))
    assert await svc.login("alice", "wrong password") is None
    assert await svc.login("nobody", PASSWORD) is None
    assert [e.action for e in audit.entries] == ["auth.login_failed"]
    assert audit.entries[0].actor == "alice"


async def test_five_failures_lock_the_account_even_for_the_right_password() -> None:
    svc, _, _, clock = await build(make_account("alice"))
    for _ in range(5):
        assert await svc.login("alice", "wrong password") is None
    assert await svc.login("alice", PASSWORD) is None  # locked
    clock.now += 901
    assert await svc.login("alice", PASSWORD) is not None


async def test_a_disabled_account_cannot_sign_in() -> None:
    svc, _, _, _ = await build(make_account("alice", disabled=True))
    assert await svc.login("alice", PASSWORD) is None


async def test_administrators_get_admin_tokens() -> None:
    root = make_account("root", Role.PLATFORM_ADMIN, None, ())
    svc, _, _, _ = await build(root)
    result = await svc.login("root", PASSWORD)
    assert result is not None
    claims = jwt.decode(result[1], ADMIN_SECRET, algorithms=["HS256"], audience="rag-admin")
    assert claims["role"] == "platform_admin" and "tenant" not in claims


async def test_admin_login_is_refused_when_the_admin_api_is_off() -> None:
    svc, _, _, _ = await build(make_account("root", Role.PLATFORM_ADMIN, None, ()), admin_secret=None)
    with pytest.raises(AdminDisabled):
        await svc.login("root", PASSWORD)


async def test_sessions_end_on_disable_and_on_password_change() -> None:
    svc, store, _, _ = await build(make_account("alice"))
    result = await svc.login("alice", PASSWORD)
    assert result is not None
    account, token = result
    assert await svc.resolve(token) is not None

    changed = await svc.change_password(account, PASSWORD, "another long password")
    assert await svc.resolve(token) is None  # the old session died
    assert await svc.resolve(svc.issue(changed)) is not None

    await store.save(replace(changed, disabled=True))
    assert await svc.resolve(svc.issue(changed)) is None


async def test_change_password_rules() -> None:
    svc, _, _, _ = await build(make_account("alice", must_change=True))
    account = (await svc.login("alice", PASSWORD) or (None,))[0]
    assert account is not None and account.must_change_password
    for current, new in (("wrong", "another long password"), (PASSWORD, "short"), (PASSWORD, PASSWORD)):
        with pytest.raises(ValueError):
            await svc.change_password(account, current, new)
    done = await svc.change_password(account, PASSWORD, "another long password")
    assert not done.must_change_password and done.token_version == 1

    