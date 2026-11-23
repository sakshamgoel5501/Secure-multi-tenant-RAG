from pathlib import Path

import pytest

from adapters.local_blobs import LocalBlobStore
from domain.models import DocumentId, TenantId

T, T2, D = TenantId("t1"), TenantId("t2"), DocumentId("d1")


async def test_round_trip_listing_and_overwrite(tmp_path: Path) -> None:
    s = LocalBlobStore(tmp_path)
    await s.put(T, D, 1, "text", b"hello")
    await s.put(T, D, 1, "original", b"%PDF")
    await s.put(T, D, 2, "text", b"v2")
    await s.put(T, D, 1, "text", b"hello again")  # overwrite
    assert await s.get(T, D, 1, "text") == b"hello again"
    assert await s.get(T, D, 3, "text") is None
    assert [(b.version, b.kind, b.size) for b in await s.list_blobs(T, D)] == [
        (1, "original", 4), (1, "text", 11), (2, "text", 2),
    ]  # fmt: skip
    assert not list(tmp_path.rglob("*.tmp"))


async def test_tenants_and_documents_are_separate_and_delete_is_scoped(tmp_path: Path) -> None:
    s = LocalBlobStore(tmp_path)
    await s.put(T, D, 1, "text", b"a")
    await s.put(T2, D, 1, "text", b"b")
    await s.put(T, DocumentId("d2"), 1, "text", b"c")
    assert await s.delete_document(T, D) == 1
    assert await s.get(T, D, 1, "text") is None
    assert await s.get(T2, D, 1, "text") == b"b" and await s.get(T, DocumentId("d2"), 1, "text") == b"c"
    assert await s.delete_document(T, D) == 0


async def test_ids_cannot_escape_the_root(tmp_path: Path) -> None:
    s = LocalBlobStore(tmp_path / "blobs")
    for tenant, doc in (("..", "d"), ("t", "../x"), ("t/u", "d"), ("t", "")):
        with pytest.raises(ValueError):
            await s.put(TenantId(tenant), DocumentId(doc), 1, "text", b"x")
    with pytest.raises(ValueError):
        await s.put(T, D, 1, "../../etc", b"x")

        