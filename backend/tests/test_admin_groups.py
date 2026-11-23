from collections.abc import Collection
from pathlib import Path

import httpx
from admin_tokens import admin_headers, admin_token
from fastapi import FastAPI

from adapters.memory_audit import InMemoryAuditLog
from adapters.memory_doc_state import InMemoryDocStateStore
from domain.models import DocStatus, DocumentEvent, DocumentId, DocumentState, GroupId, TenantId
from ingestion.purge import Purger
from serving.admin import create_admin_router

KEY = "k" * 32
T1, T2 = TenantId("t1"), TenantId("t2")
T1ADMIN = admin_headers(KEY, "tenant_admin", "t1")
D_ENG, D_HR, D_BOTH = DocumentId("d-eng"), DocumentId("d-hr"), DocumentId("d-both")
ENG = admin_headers(KEY, "group_admin", "t1", "eng")
PLATFORM = admin_headers(KEY)


class Scanner:
    async def list_tenants(self) -> list[TenantId]:
        return [T1, T2]

    async def list_states(self, tenant_id: TenantId) -> list[DocumentState]:
        if tenant_id != T1:
            return []
        return [DocumentState(d, T1, 1, 1, DocStatus.ACTIVE) for d in (D_ENG, D_HR, D_BOTH)]


class Acls:
    def __init__(self) -> None:
        self.data: dict[tuple[TenantId, DocumentId], frozenset[GroupId]] = {
            (T1, D_ENG): frozenset({GroupId("eng")}),
            (T1, D_HR): frozenset({GroupId("hr")}),
            (T1, D_BOTH): frozenset({GroupId("eng"), GroupId("hr")}),
        }
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


class Bus:
    async def pending_count(self) -> int:
        return 1

    async def dlq_entries(self) -> list[dict[str, str]]:
        return [{"original_id": "1-0", "error": "boom", "deliveries": "5", "data": "SECRET TEXT"}]


class Events:
    async def count_document_events(self, tenant_id: TenantId, document_id: DocumentId) -> int:
        return 0

    async def purge_document_events(self, tenant_id: TenantId, document_id: DocumentId) -> int:
        return 0


class Pub:
    def __init__(self) -> None:
        self.events: list[DocumentEvent] = []

    async def publish(self, event: DocumentEvent) -> str:
        self.events.append(event)
        return "1-0"


async def build(tmp_path: Path) -> tuple[httpx.AsyncClient, Acls, InMemoryAuditLog, Pub, InMemoryDocStateStore]:
    state = InMemoryDocStateStore()
    for d in (D_ENG, D_HR, D_BOTH):
        await state.promote(T1, d, 1)
    acls, audit, pub = Acls(), InMemoryAuditLog(), Pub()
    app = FastAPI()
    app.include_router(
        create_admin_router(
            state, Scanner(), acls, Bus(), admin_key=KEY, data_dir=tmp_path, audit=audit,
            publisher=pub, purger=Purger(state, acls, {}, Events()),
        )
    )  # fmt: skip
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, acls, audit, pub, state


async def test_group_token_needs_tenant_and_group(tmp_path: Path) -> None:
    c, *_ = await build(tmp_path)
    for token in (admin_token(KEY, "group_admin", "t1"), admin_token(KEY, "group_admin", group="eng")):
        assert (await c.get("/admin/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401


async def test_group_admin_sees_only_documents_their_group_can_read(tmp_path: Path) -> None:
    c, *_ = await build(tmp_path)
    r = await c.get("/admin/documents", params={"tenant": "t1"}, headers=ENG)
    assert {d["document_id"] for d in r.json()["documents"]} == {"d-eng", "d-both"}
    assert r.json()["total"] == 2
    assert (await c.get("/admin/documents", params={"tenant": "t2"}, headers=ENG)).status_code == 403


async def test_a_hidden_document_looks_the_same_as_a_missing_one(tmp_path: Path) -> None:
    c, _, audit, *_ = await build(tmp_path)
    hidden = await c.get("/admin/documents/d-hr", params={"tenant": "t1"}, headers=ENG)
    missing = await c.get("/admin/documents/d-nope", params={"tenant": "t1"}, headers=ENG)
    assert hidden.status_code == missing.status_code == 403
    assert audit.entries[-1].action == "denied:document.read"
    assert (await c.get("/admin/documents/d-eng", params={"tenant": "t1"}, headers=ENG)).status_code == 200


async def test_group_admin_cannot_change_access_to_a_document_they_cannot_see(tmp_path: Path) -> None:
    c, acls, *_ = await build(tmp_path)
    r = await c.put("/admin/documents/d-hr/acl", json={"tenant_id": "t1", "groups": ["eng"]}, headers=ENG)
    assert r.status_code == 403 and acls.epoch == 0


async def test_group_admin_may_share_but_not_remove_their_own_group(tmp_path: Path) -> None:
    c, acls, *_ = await build(tmp_path)
    shared = await c.put("/admin/documents/d-eng/acl", json={"tenant_id": "t1", "groups": ["eng", "hr"]}, headers=ENG)
    assert shared.status_code == 200
    dropped = await c.put("/admin/documents/d-eng/acl", json={"tenant_id": "t1", "groups": ["hr"]}, headers=ENG)
    assert dropped.status_code == 403 and "own group" in dropped.json()["detail"]
    assert acls.data[(T1, D_ENG)] == frozenset({GroupId("eng"), GroupId("hr")})


async def test_a_tenant_admin_can_remove_the_group_a_group_admin_cannot(tmp_path: Path) -> None:
    c, acls, *_ = await build(tmp_path)
    r = await c.put(
        "/admin/documents/d-eng/acl", json={"tenant_id": "t1", "groups": ["hr"]},
        headers=admin_headers(KEY, "tenant_admin", "t1"),
    )  # fmt: skip
    assert r.status_code == 200 and acls.data[(T1, D_ENG)] == frozenset({GroupId("hr")})


async def test_group_admin_documents_must_include_their_group(tmp_path: Path) -> None:
    c, _, _, pub, _ = await build(tmp_path)
    body = {"tenant_id": "t1", "title": "x", "text": "y", "groups": ["hr"]}
    assert (await c.post("/admin/documents", json=body, headers=ENG)).status_code == 403
    assert pub.events == []
    ok = await c.post("/admin/documents", json={**body, "groups": ["eng", "hr"]}, headers=ENG)
    assert ok.status_code == 201 and len(pub.events) == 1


async def test_group_admin_cannot_purge_simulate_or_read_the_audit_log(tmp_path: Path) -> None:
    c, _, audit, _, state = await build(tmp_path)
    purge = await c.post("/admin/documents/d-eng/purge", params={"tenant": "t1"}, headers=ENG)
    assert purge.status_code == 403 and "purge" in purge.json()["detail"]
    after = await state.get(T1, D_ENG)
    assert after is not None and after.is_searchable
    sim = await c.post(
        "/admin/simulate",
        json={"tenant_id": "t1", "document_id": "d-eng", "scenario": "slow_update", "title": "t", "text": "x"},
        headers=ENG,
    )
    assert sim.status_code == 403
    assert (await c.get("/admin/audit", headers=ENG)).status_code == 403
    assert audit.entries[-1].action == "denied:audit.read"


async def test_reads_are_audited_once_per_window(tmp_path: Path) -> None:
    c, _, audit, *_ = await build(tmp_path)
    for _ in range(3):
        await c.get("/admin/documents", params={"tenant": "t1"}, headers=T1ADMIN)
    reads = [e for e in audit.entries if e.action == "read:documents.list"]
    assert len(reads) == 1 and reads[0].role == "tenant_admin"


async def test_a_failing_audit_store_does_not_block_reads(tmp_path: Path) -> None:
    c, _, audit, *_ = await build(tmp_path)
    audit.fail = True
    assert (await c.get("/admin/documents", params={"tenant": "t1"}, headers=T1ADMIN)).status_code == 200


async def test_the_dead_letter_view_never_returns_document_text(tmp_path: Path) -> None:
    c, *_ = await build(tmp_path)
    r = await c.get("/admin/dlq", headers=PLATFORM)
    assert r.status_code == 200 and "SECRET TEXT" not in r.text
    assert r.json()["entries"][0]["error"] == "boom"


async def test_group_admin_can_version_and_delete_documents_their_group_can_read(tmp_path: Path) -> None:
    c, _, _, pub, _ = await build(tmp_path)
    body = {"tenant_id": "t1", "title": "t", "text": "new text"}
    v = await c.post("/admin/documents/d-eng/versions", json=body, headers=ENG)
    assert v.status_code == 202 and v.json()["version"] == 2
    d = await c.delete("/admin/documents/d-eng", params={"tenant": "t1"}, headers=ENG)
    assert d.status_code == 202 and d.json()["version"] == 3
    assert len(pub.events) == 2
    hidden = await c.post("/admin/documents/d-hr/versions", json=body, headers=ENG)
    assert hidden.status_code == 403 and len(pub.events) == 2

    

    