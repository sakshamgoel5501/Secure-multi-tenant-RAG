from collections.abc import Collection
from pathlib import Path

import httpx
from fastapi import FastAPI

from adapters.memory_audit import InMemoryAuditLog
from adapters.memory_doc_state import InMemoryDocStateStore
from admin_tokens import admin_headers
from domain.models import (
    ChunkId, DocStatus, DocumentId, DocumentState, GroupId,
    RetrievalSource, SearchHit, SecurityContext, TenantId,
)  # fmt: skip
from serving.admin import create_admin_router

KEY = "k" * 32
T1 = TenantId("t1")
D = DocumentId("d1")
BOSS = admin_headers(KEY, "tenant_admin", "t1")


class Scanner:
    async def list_tenants(self) -> list[TenantId]:
        return [T1]

    async def list_states(self, tenant_id: TenantId) -> list[DocumentState]:
        return [DocumentState(D, T1, 1, 1, DocStatus.ACTIVE)]


class Acls:
    data = {(T1, D): frozenset({GroupId("eng")})}

    async def list_acls(self, tenant_id: TenantId) -> dict[DocumentId, frozenset[GroupId]]:
        return {d: g for (t, d), g in self.data.items() if t == tenant_id}

    async def set_acl(self, tenant_id: TenantId, document_id: DocumentId, groups: Collection[GroupId]) -> int:
        return 1


class Bus:
    async def pending_count(self) -> int:
        return 0

    async def dlq_entries(self) -> list[dict[str, str]]:
        return []


class Epochs:
    async def current_epoch(self) -> int:
        return 9


async def searcher(ctx: SecurityContext, query: str, top_k: int) -> list[SearchHit]:
    if GroupId("eng") in ctx.group_ids and query == "needle" and ctx.policy_epoch == 9:
        return [
            SearchHit(ChunkId("d1:3:0"), T1, D, 3, "t", None, 0, 1, "SECRET", 1.0, RetrievalSource.HYBRID)
        ]
    return []


async def client(tmp_path: Path) -> httpx.AsyncClient:
    state = InMemoryDocStateStore()
    await state.promote(T1, D, 1)
    app = FastAPI()
    app.include_router(
        create_admin_router(
            state, Scanner(), Acls(), Bus(), admin_key=KEY, data_dir=tmp_path,
            audit=InMemoryAuditLog(), searcher=searcher, epochs=Epochs(),
        )
    )  # fmt: skip
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def body(group: str, query: str = "needle") -> dict[str, str]:
    return {"tenant_id": "t1", "group": group, "query": query}


async def test_probe_reports_yes_or_no_and_a_version_never_text(tmp_path: Path) -> None:
    c = await client(tmp_path)
    yes = await c.post("/admin/documents/d1/probe", json=body("eng"), headers=BOSS)
    assert yes.json() == {"found": True, "version": 3} and "SECRET" not in yes.text
    no = await c.post("/admin/documents/d1/probe", json=body("hr"), headers=BOSS)
    assert no.json() == {"found": False, "version": None}


async def test_probe_follows_the_same_scope_rules_as_other_routes(tmp_path: Path) -> None:
    c = await client(tmp_path)
    platform = await c.post("/admin/documents/d1/probe", json=body("eng"), headers=admin_headers(KEY))
    assert platform.status_code == 403
    other_group = admin_headers(KEY, "group_admin", "t1", "hr")  # d1 is readable by eng only
    assert (await c.post("/admin/documents/d1/probe", json=body("eng"), headers=other_group)).status_code == 403
    mine = admin_headers(KEY, "group_admin", "t1", "eng")
    assert (await c.post("/admin/documents/d1/probe", json=body("eng"), headers=mine)).status_code == 200

    