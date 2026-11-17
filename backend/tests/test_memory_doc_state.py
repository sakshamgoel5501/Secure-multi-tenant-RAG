import asyncio

import pytest

from adapters.memory_doc_state import InMemoryDocStateStore
from domain.models import DocumentId, PromotionOutcome, TenantId
from domain.ports import DocStateStore

T = TenantId("t1")
D = DocumentId("d1")


def make_store() -> DocStateStore:
    # Annotating as the Protocol makes mypy verify the fake matches the port.
    return InMemoryDocStateStore()


async def test_record_seen_is_idempotent_and_monotonic() -> None:
    store = make_store()
    await store.record_seen(T, D, 5)
    await store.record_seen(T, D, 3)  # late event must not lower it
    await store.record_seen(T, D, 5)  # duplicate
    state = await store.get(T, D)
    assert state is not None
    assert state.latest_seen_version == 5
    assert state.active_version is None


async def test_in_progress_version_keeps_old_one_searchable() -> None:
    store = make_store()
    await store.promote(T, D, 10)
    await store.record_seen(T, D, 11)  # v11 being indexed, not promoted yet
    state = await store.get(T, D)
    assert state is not None
    assert state.active_version == 10
    assert state.latest_seen_version == 11
    assert state.is_searchable


async def test_duplicate_promote_is_already_active() -> None:
    store = make_store()
    assert await store.promote(T, D, 10) is PromotionOutcome.PROMOTED
    assert await store.promote(T, D, 10) is PromotionOutcome.ALREADY_ACTIVE


async def test_late_old_version_cannot_overwrite_newer() -> None:
    store = make_store()
    assert await store.promote(T, D, 11) is PromotionOutcome.PROMOTED
    assert await store.promote(T, D, 10) is PromotionOutcome.STALE
    state = await store.get(T, D)
    assert state is not None and state.active_version == 11


async def test_late_update_after_tombstone_is_stale() -> None:
    store = make_store()
    await store.promote(T, D, 10)
    await store.tombstone(T, D, 12)
    assert await store.promote(T, D, 11) is PromotionOutcome.STALE
    state = await store.get(T, D)
    assert state is not None and not state.is_searchable


async def test_old_tombstone_cannot_kill_newer_version() -> None:
    store = make_store()
    await store.promote(T, D, 13)
    await store.tombstone(T, D, 12)  # delete event arrives late
    state = await store.get(T, D)
    assert state is not None and state.is_searchable
    assert state.active_version == 13


async def test_newer_version_revives_deleted_document() -> None:
    store = make_store()
    await store.tombstone(T, D, 12)
    assert await store.promote(T, D, 13) is PromotionOutcome.PROMOTED
    state = await store.get(T, D)
    assert state is not None and state.is_searchable


async def test_tenants_are_isolated() -> None:
    store = make_store()
    await store.promote(T, D, 10)
    assert await store.get(TenantId("other"), D) is None


@pytest.mark.parametrize("order", [(10, 11), (11, 10)])
async def test_concurrent_workers_never_regress(order: tuple[int, int]) -> None:
    store = make_store()
    a, b = order
    results = await asyncio.gather(store.promote(T, D, a), store.promote(T, D, b))
    state = await store.get(T, D)
    assert state is not None
    assert state.active_version == 11  # whichever worker ran first, v11 always wins
    assert results[order.index(11)] is PromotionOutcome.PROMOTED


async def test_get_many_is_tenant_scoped_and_skips_unknown() -> None:
    store = make_store()
    await store.promote(T, D, 1)
    found = await store.get_many(T, [D, DocumentId("nope")])
    assert set(found) == {D}
    assert await store.get_many(TenantId("other"), [D]) == {}

    