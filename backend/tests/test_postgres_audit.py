import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from adapters.postgres_audit import PostgresAuditLog
from domain.ops_ports import AuditEntry

DSN = os.environ.get("RAG_PG_DSN")
pytestmark = pytest.mark.skipif(DSN is None, reason="set RAG_PG_DSN to a scratch database")


@pytest_asyncio.fixture
async def log() -> AsyncIterator[PostgresAuditLog]:
    assert DSN is not None
    s = PostgresAuditLog(DSN)
    await s.start()
    await s.reset()
    yield s
    await s.close()


async def test_entries_round_trip_newest_first_and_filter_by_tenant(log: PostgresAuditLog) -> None:
    await log.record(AuditEntry("a", "tenant_admin", "t1", "acl.set", "d1", {"after": ["hr"]}))
    await log.record(AuditEntry("b", "platform_admin", "t2", "document.purge", "d2"))
    everything = await log.list_entries(None, 10)
    assert [e.target for e in everything] == ["d2", "d1"]
    only_t1 = await log.list_entries("t1", 10)
    assert [e.detail for e in only_t1] == [{"after": ["hr"]}]
    assert only_t1[0].at != ""


    