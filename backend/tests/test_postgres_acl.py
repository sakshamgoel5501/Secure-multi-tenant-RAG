"""
skipped unless RAG_PG_DSN is set
"""

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from adapters.postgres_acl import PostgresAclStore
from domain.errors import AuthzUnavailable
from domain.models import DocumentId, GroupId, TenantId
from domain.ports import AclReader

DSN = os.environ.get("RAG_PG_DSN")
pytestmark = pytest.mark.skipif(DSN is None, reason="set RAG_PG_DSN to a scratch database")

T = TenantId("t1")
D = DocumentId("d1")
G1 = GroupId("g1")
G2 = GroupId("g2")


@pytest_asyncio.fixture
async def store() -> AsyncIterator[PostgresAclStore]:
    assert DSN is not None
    s = PostgresAclStore(DSN)
    await s.start()
    await s.reset()
    yield s
    await s.close()


async def test_set_acl_returns_increasing_epochs_and_reader_sees_groups(
    store: PostgresAclStore,
) -> None:
    reader: AclReader = store  # mypy checks the adapter satisfies the port
    e1 = await store.set_acl(T, D, {G1})
    e2 = await store.set_acl(T, DocumentId("d2"), {G1, G2})
    assert e2 == e1 + 1
    snap = await reader.acls_for(T, [D, DocumentId("d2")], min_epoch=e2)
    assert snap.epoch == e2
    assert snap.acls[D] == frozenset({G1})
    assert snap.acls[DocumentId("d2")] == frozenset({G1, G2})


async def test_missing_acl_is_absent(store: PostgresAclStore) -> None:
    epoch = await store.set_acl(T, D, {G1})
    snap = await store.acls_for(T, [D, DocumentId("nope")], min_epoch=epoch)
    assert set(snap.acls) == {D}  # absent means "no grants", never "allow"


async def test_acls_are_tenant_scoped(store: PostgresAclStore) -> None:
    epoch = await store.set_acl(TenantId("t2"), D, {G1})
    snap = await store.acls_for(T, [D], min_epoch=epoch)
    assert snap.acls == {}


async def test_revocation_visible_at_returned_epoch(store: PostgresAclStore) -> None:
    await store.set_acl(T, D, {G1})
    e2 = await store.set_acl(T, D, {G2})  # g1 removed
    snap = await store.acls_for(T, [D], min_epoch=e2)
    assert snap.acls[D] == frozenset({G2})


async def test_reader_behind_required_epoch_fails_closed(store: PostgresAclStore) -> None:
    epoch = await store.set_acl(T, D, {G1})
    with pytest.raises(AuthzUnavailable):
        await store.acls_for(T, [D], min_epoch=epoch + 1)


async def test_epochs_are_unique_under_concurrency(store: PostgresAclStore) -> None:
    epochs = await asyncio.gather(
        *(store.set_acl(T, DocumentId(f"doc{i}"), {G1}) for i in range(30))
    )
    assert sorted(epochs) == list(range(1, 31))
    assert await store.current_epoch() == 30


async def test_list_acls_is_tenant_scoped(store: PostgresAclStore) -> None:
    await store.set_acl(T, D, {G1, G2})
    await store.set_acl(TenantId("t2"), DocumentId("x"), {G1})
    assert await store.list_acls(T) == {D: frozenset({G1, G2})}



