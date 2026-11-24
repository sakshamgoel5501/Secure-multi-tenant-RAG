import asyncio
import os
import random
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from adapters.postgres_doc_state import PostgresDocStateStore
from domain.models import DocumentId, PromotionOutcome, TenantId

DSN = os.environ.get("RAG_PG_DSN")
pytestmark = pytest.mark.skipif(DSN is None, reason="set RAG_PG_DSN to a scratch database")

T = TenantId("t1")
D = DocumentId("d1")


@pytest_asyncio.fixture
async def store() -> AsyncIterator[PostgresDocStateStore]:
    assert DSN is not None
    s = PostgresDocStateStore(DSN)
    await s.start()
    await s.reset()
    yield s
    await s.close()


async def test_record_seen_is_idempotent_and_monotonic(store: PostgresDocStateStore) -> None:
    await store.record_seen(T, D, 5)
    await store.record_seen(T, D, 3)
    await store.record_seen(T, D, 5)
    state = await store.get(T, D)
    assert state is not None
    assert state.latest_seen_version == 5
    assert state.active_version is None


async def test_in_progress_version_keeps_old_one_searchable(store: PostgresDocStateStore) -> None:
    await store.promote(T, D, 10)
    await store.record_seen(T, D, 11)
    state = await store.get(T, D)
    assert state is not None
    assert (state.active_version, state.latest_seen_version) == (10, 11)
    assert state.is_searchable


async def test_duplicate_promote_is_already_active(store: PostgresDocStateStore) -> None:
    assert await store.promote(T, D, 10) is PromotionOutcome.PROMOTED
    assert await store.promote(T, D, 10) is PromotionOutcome.ALREADY_ACTIVE


async def test_late_old_version_cannot_overwrite_newer(store: PostgresDocStateStore) -> None:
    assert await store.promote(T, D, 11) is PromotionOutcome.PROMOTED
    assert await store.promote(T, D, 10) is PromotionOutcome.STALE
    state = await store.get(T, D)
    assert state is not None and state.active_version == 11


async def test_late_update_after_tombstone_is_stale(store: PostgresDocStateStore) -> None:
    await store.promote(T, D, 10)
    await store.tombstone(T, D, 12)
    assert await store.promote(T, D, 11) is PromotionOutcome.STALE
    state = await store.get(T, D)
    assert state is not None and not state.is_searchable


async def test_old_tombstone_cannot_kill_newer_version(store: PostgresDocStateStore) -> None:
    await store.promote(T, D, 13)
    await store.tombstone(T, D, 12)
    state = await store.get(T, D)
    assert state is not None and state.is_searchable and state.active_version == 13


async def test_newer_version_revives_deleted_document(store: PostgresDocStateStore) -> None:
    await store.tombstone(T, D, 12)
    assert await store.promote(T, D, 13) is PromotionOutcome.PROMOTED
    state = await store.get(T, D)
    assert state is not None and state.is_searchable


async def test_tenants_are_isolated(store: PostgresDocStateStore) -> None:
    await store.promote(T, D, 10)
    assert await store.get(TenantId("other"), D) is None


async def test_get_many_is_tenant_scoped_and_skips_unknown(store: PostgresDocStateStore) -> None:
    await store.promote(T, D, 1)
    found = await store.get_many(T, [D, DocumentId("nope")])
    assert set(found) == {D}
    assert await store.get_many(TenantId("other"), [D]) == {}


async def test_concurrent_promotes_converge_to_highest_version(
    store: PostgresDocStateStore,
) -> None:
    for round_no in range(5):
        doc = DocumentId(f"race-{round_no}")
        versions = list(range(1, 41))
        random.shuffle(versions)
        results = await asyncio.gather(*(store.promote(T, doc, v) for v in versions))
        state = await store.get(T, doc)
        assert state is not None and state.active_version == 40
        assert results[versions.index(40)] is PromotionOutcome.PROMOTED
        assert PromotionOutcome.ALREADY_ACTIVE not in results  # every version is unique


async def test_purged_flag_is_set_and_cleared_by_a_newer_version(store: PostgresDocStateStore) -> None:
    await store.promote(T, D, 1)
    await store.tombstone(T, D, 2)
    await store.mark_purged(T, D)
    s = await store.get(T, D)
    assert s is not None and s.purged
    await store.promote(T, D, 3)
    s = await store.get(T, D)
    assert s is not None and not s.purged

    

        