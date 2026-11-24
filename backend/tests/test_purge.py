from collections.abc import Collection
from pathlib import Path

import httpx
import pytest
from admin_tokens import admin_headers
from fastapi import FastAPI

from adapters.memory_audit import InMemoryAuditLog
from adapters.memory_blobs import InMemoryBlobStore
from adapters.memory_doc_state import InMemoryDocStateStore
from domain.models import DocumentId, DocumentState, GroupId, PromotionOutcome, TenantId
from ingestion.purge import Purger
from serving.admin import create_admin_router

T = TenantId("t1")
OTHER = TenantId("t2")
D = DocumentId("d1")
KEY = "k" * 32
H = admin_headers(KEY, "tenant_admin", "t1")
_Key = tuple[TenantId, DocumentId]


class FakeIndex:
    def __init__(self, data: dict[_Key, dict[int, int]]) -> None:
        self.data = data

    async def document_versions(self, tenant_id: TenantId, document_id: DocumentId) -> dict[int, int]:
        return dict(self.data.get((tenant_id, document_id), {}))

    async def delete_versions(
        self, tenant_id: TenantId, document_id: DocumentId, versions: Collection[int]
    ) -> int:
        current = self.data.get((tenant_id, document_id), {})
        removed = sum(current.pop(v, 0) for v in list(versions))
        if not current:
            self.data.pop((tenant_id, document_id), None)
        return removed


class FakeEvents:
    def __init__(self, counts: dict[_Key, int]) -> None:
        self.counts = counts

    async def count_document_events(self, tenant_id: TenantId, document_id: DocumentId) -> int:
        return self.counts.get((tenant_id, document_id), 0)

    async def purge_document_events(self, tenant_id: TenantId, document_id: DocumentId) -> int:
        return self.counts.pop((tenant_id, document_id), 0)


class FakeAcls:
    def __init__(self) -> None:
        self.data: dict[_Key, frozenset[GroupId]] = {}
        self.epoch = 0

    async def list_acls(self, tenant_id: TenantId) -> dict[DocumentId, frozenset[GroupId]]:
        return {d: g for (t, d), g in self.data.items() if t == tenant_id}

    async def set_acl(
        self, tenant_id: TenantId, document_id: DocumentId, groups: Collection[GroupId]
    ) -> int:
        self.epoch += 1
        self.data[(tenant_id, document_id)] = frozenset(groups)
        return self.epoch

    async def delete_acl(self, tenant_id: TenantId, document_id: DocumentId) -> int:
        self.epoch += 1
        self.data.pop((tenant_id, document_id), None)
        return self.epoch


class Scanner:
    async def list_tenants(self) -> list[TenantId]:
        return []

    async def list_states(self, tenant_id: TenantId) -> list[DocumentState]:
        return []


class Dlq:
    async def pending_count(self) -> int:
        return 0

    async def dlq_entries(self) -> list[dict[str, str]]:
        return []


class Env:
    def __init__(self) -> None:
        self.state = InMemoryDocStateStore()
        self.dense = FakeIndex({(T, D): {1: 3}, (OTHER, D): {1: 2}})
        self.lexical = FakeIndex({(T, D): {1: 3}})
        self.events = FakeEvents({(T, D): 2})
        self.acls = FakeAcls()
        self.acls.data[(T, D)] = frozenset({GroupId("eng")})
        self.acls.data[(OTHER, D)] = frozenset({GroupId("eng")})
        self.purger = Purger(
            self.state, self.acls, {"dense": self.dense, "lexical": self.lexical}, self.events
        )


async def env() -> Env:
    e = Env()
    await e.state.promote(T, D, 1)
    await e.state.promote(OTHER, D, 1)
    return e


async def test_footprint_lists_everything_stored() -> None:
    e = await env()
    fp = await e.purger.footprint(T, D)
    assert fp.chunks == {"dense": {1: 3}, "lexical": {1: 3}}
    assert fp.has_acl and fp.events == 2 and fp.content_left


async def test_purge_removes_every_trace_but_keeps_a_content_free_tombstone() -> None:
    e = await env()
    report = await e.purger.purge(T, D)
    assert report.chunks_deleted == {"dense": 3, "lexical": 3}
    assert report.events_deleted == 2 and report.acl_removed and report.epoch is not None
    assert not report.after.content_left
    state = await e.state.get(T, D)
    assert state is not None and not state.is_searchable and state.status.value == "deleted"


async def test_purge_leaves_other_tenants_untouched() -> None:
    e = await env()
    await e.purger.purge(T, D)
    assert e.dense.data[(OTHER, D)] == {1: 2}
    assert (OTHER, D) in e.acls.data


async def test_old_events_cannot_resurrect_a_purged_document() -> None:
    e = await env()
    await e.purger.purge(T, D)
    assert await e.state.promote(T, D, 1) is PromotionOutcome.STALE
    assert await e.state.promote(T, D, 2) is PromotionOutcome.STALE
    assert await e.state.promote(T, D, 3) is PromotionOutcome.PROMOTED  # a genuinely newer version


async def test_purging_twice_is_harmless() -> None:
    e = await env()
    await e.purger.purge(T, D)
    second = await e.purger.purge(T, D)
    assert second.chunks_deleted == {"dense": 0, "lexical": 0}
    assert second.events_deleted == 0 and not second.acl_removed


async def test_purging_an_unknown_document_raises() -> None:
    e = await env()
    with pytest.raises(KeyError):
        await e.purger.purge(T, DocumentId("nope"))


async def client(e: Env, tmp_path: Path) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(
        create_admin_router(
            e.state, Scanner(), e.acls, Dlq(), admin_key=KEY, data_dir=tmp_path, purger=e.purger, audit=InMemoryAuditLog(),
        )
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_admin_routes_report_and_purge(tmp_path: Path) -> None:
    c = await client(await env(), tmp_path)
    assert (await c.get("/admin/capabilities", headers=H)).json() == {
        "lifecycle": False, 
        "purge": True, 
        "files": False,
    }
    before = (await c.get("/admin/documents/d1/footprint", params={"tenant": "t1"}, headers=H)).json()
    assert before["content_left"] is True
    r = await c.post("/admin/documents/d1/purge", params={"tenant": "t1"}, headers=H)
    assert r.status_code == 200 and r.json()["after"]["content_left"] is False


async def test_purge_needs_the_key_and_a_known_document(tmp_path: Path) -> None:
    c = await client(await env(), tmp_path)
    assert (await c.post("/admin/documents/d1/purge", params={"tenant": "t1"})).status_code == 401
    r = await c.post("/admin/documents/nope/purge", params={"tenant": "t1"}, headers=H)
    assert r.status_code == 404 and r.json()["detail"] == "unknown document"


async def test_footprint_marks_chunks_that_are_not_the_live_version(tmp_path: Path) -> None:
    e = await env()
    e.dense.data[(T, D)][2] = 2  # leftovers of a write that never got promoted
    c = await client(e, tmp_path)
    body = (await c.get("/admin/documents/d1/footprint", params={"tenant": "t1"}, headers=H)).json()
    assert body["live_version"] == 1
    assert body["unreachable"] == {"dense": {"2": 2}, "lexical": {}}


async def test_after_a_delete_every_chunk_is_unreachable(tmp_path: Path) -> None:
    e = await env()
    await e.state.tombstone(T, D, 5)
    c = await client(e, tmp_path)
    body = (await c.get("/admin/documents/d1/footprint", params={"tenant": "t1"}, headers=H)).json()
    assert body["live_version"] is None
    assert body["unreachable"] == {"dense": {"1": 3}, "lexical": {"1": 3}}

    
async def test_purge_removes_stored_files_but_only_for_that_document(tmp_path: Path) -> None:
    e = await env()
    blobs = InMemoryBlobStore()
    await blobs.put(T, D, 1, "text", b"secret text")
    await blobs.put(T, D, 1, "original", b"%PDF")
    await blobs.put(OTHER, D, 1, "text", b"someone else's")
    purger = Purger(e.state, e.acls, {"dense": e.dense, "lexical": e.lexical}, e.events, blobs=blobs)
    before = await purger.footprint(T, D)
    assert before.blobs == 2 and before.content_left
    report = await purger.purge(T, D)
    assert report.blobs_deleted == 2 and not report.after.content_left
    assert await blobs.get(OTHER, D, 1, "text") == b"someone else's"


async def test_the_footprint_route_lists_stored_files(tmp_path: Path) -> None:
    e = await env()
    blobs = InMemoryBlobStore()
    await blobs.put(T, D, 1, "text", b"abc")
    purger = Purger(e.state, e.acls, {"dense": e.dense, "lexical": e.lexical}, e.events, blobs=blobs)
    app = FastAPI()
    app.include_router(
        create_admin_router(
            e.state, Scanner(), e.acls, Dlq(), admin_key=KEY, data_dir=tmp_path,
            audit=InMemoryAuditLog(), purger=purger, blobs=blobs,
        )
    )  # fmt: skip
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    body = (await c.get("/admin/documents/d1/footprint", params={"tenant": "t1"}, headers=H)).json()
    assert body["files"] == [{"version": 1, "kind": "text", "bytes": 3}] and body["blobs"] == 1


async def test_access_cannot_be_changed_on_a_deleted_document(tmp_path: Path) -> None:
    e = await env()
    c = await client(e, tmp_path)
    await c.post("/admin/documents/d1/purge", params={"tenant": "t1"}, headers=H)
    r = await c.put("/admin/documents/d1/acl", json={"tenant_id": "t1", "groups": ["eng"]}, headers=H)
    assert r.status_code == 409
    assert (T, D) not in e.acls.data

    
    