import os
from collections.abc import AsyncIterator
from dataclasses import replace

import pytest
import pytest_asyncio
from account_helpers import make_account

from adapters.postgres_accounts import PostgresAccountStore
from domain.accounts import Role

DSN = os.environ.get("RAG_PG_DSN")
pytestmark = pytest.mark.skipif(DSN is None, reason="set RAG_PG_DSN to a scratch database")


@pytest_asyncio.fixture
async def store() -> AsyncIterator[PostgresAccountStore]:
    assert DSN is not None
    s = PostgresAccountStore(DSN)
    await s.start()
    await s.reset()
    yield s
    await s.close()


async def test_create_get_save_delete_round_trip(store: PostgresAccountStore) -> None:
    alice = make_account("alice", groups=("eng", "hr"))
    assert await store.create(alice) and not await store.create(alice)
    got = await store.get("alice")
    assert got is not None and got.groups == ("eng", "hr") and got.role is Role.USER and got.created_at
    await store.save(replace(got, failed_attempts=3, locked_until=12.5, last_login="2026-01-01T00:00:00+00:00"))
    again = await store.get("alice")
    assert again is not None and again.failed_attempts == 3 and again.locked_until == 12.5
    assert again.last_login.startswith("2026-01-01")
    assert await store.delete("alice") and not await store.delete("alice")


async def test_listing_and_active_platform_admin_count(store: PostgresAccountStore) -> None:
    await store.create(make_account("alice"))
    await store.create(make_account("bob", tenant="t2"))
    root = make_account("root", Role.PLATFORM_ADMIN, None, ())
    await store.create(root)
    assert [a.username for a in await store.list_accounts("t1", 10)] == ["alice"]
    assert len(await store.list_accounts(None, 10)) == 3
    assert await store.count_active_platform_admins() == 1
    await store.save(replace(root, disabled=True))
    assert await store.count_active_platform_admins() == 0

    