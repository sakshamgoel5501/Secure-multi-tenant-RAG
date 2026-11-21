import asyncio
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from admin_tokens import admin_headers
from fastapi import FastAPI

from adapters.fake_embedder import HashEmbedder
from adapters.memory_audit import InMemoryAuditLog
from adapters.memory_doc_state import InMemoryDocStateStore
from adapters.memory_vector_store import InMemoryVectorStore
from adapters.simple_chunker import ParagraphChunker
from domain.models import (
    DocStatus,
    DocumentEvent,
    DocumentId,
    DocumentState,
    GroupId,
    SecurityContext,
    TenantId,
    UserId,
)
from ingestion.worker import IngestionWorker
from serving.admin import create_admin_router

KEY = "k" * 32
H = admin_headers(KEY)
T = TenantId("t1")
CTX = SecurityContext(T, UserId("u"), frozenset({GroupId("g")}), 1)


class Scanner:
    async def list_tenants(self) -> list[TenantId]:
        return []

    async def list_states(self, tenant_id: TenantId) -> list[DocumentState]:
        return []


class Acls:
    def __init__(self) -> None:
        self.data: dict[tuple[TenantId, DocumentId], frozenset[GroupId]] = {}
        self.epoch = 0

    async def list_acls(self, tenant_id: TenantId) -> dict[DocumentId, frozenset[GroupId]]:
        return {d: g for (t, d), g in self.data.items() if t == tenant_id}

    async def set_acl(
        self, tenant_id: TenantId, document_id: DocumentId, groups: Collection[GroupId]
    ) -> int:
        self.epoch += 1
        self.data[(tenant_id, document_id)] = frozenset(groups)
        return self.epoch


class Dlq:
    async def pending_count(self) -> int:
        return 0

    async def dlq_entries(self) -> list[dict[str, str]]:
        return []


class InlineBus:
    """Delivers each published event straight to the ingestion worker."""

    def __init__(self, worker: IngestionWorker) -> None:
        self.worker = worker
        self.events: list[DocumentEvent] = []
        self.down = False

    async def publish(self, event: DocumentEvent) -> str:
        if self.down:
            raise ConnectionError("redis down")
        self.events.append(event)
        await self.worker.handle(event)
        return "1-0"


@dataclass
class Env:
    client: httpx.AsyncClient
    state: InMemoryDocStateStore
    vectors: InMemoryVectorStore
    acls: Acls
    bus: InlineBus


def build(tmp_path: Path) -> Env:
    state = InMemoryDocStateStore()
    vectors = InMemoryVectorStore()
    worker = IngestionWorker(state, vectors, ParagraphChunker(max_chars=400), HashEmbedder())
    bus = InlineBus(worker)
    acls = Acls()
    app = FastAPI()
    app.include_router(
        create_admin_router(
            state, Scanner(), acls, Dlq(), admin_key=KEY, data_dir=tmp_path, publisher=bus, audit=InMemoryAuditLog(),
        )
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return Env(client, state, vectors, acls, bus)


async def create(env: Env) -> str:
    r = await env.client.post(
        "/admin/documents",
        json={"tenant_id": "t1", "title": "Doc", "text": "launch code ALPHA", "groups": ["eng"]},
        headers=H,
    )
    assert r.status_code == 201
    doc_id: str = r.json()["document_id"]
    return doc_id


async def detail(env: Env, doc_id: str, tenant: str = "t1") -> httpx.Response:
    return await env.client.get(f"/admin/documents/{doc_id}", params={"tenant": tenant}, headers=H)


async def simulate(env: Env, doc_id: str, scenario: str, **extra: Any) -> httpx.Response:
    body = {
        "tenant_id": "t1",
        "document_id": doc_id,
        "scenario": scenario,
        "title": "Doc",
        "text": "launch code BRAVO",
        **extra,
    }
    return await env.client.post("/admin/simulate", json=body, headers=H)


async def test_create_sets_acl_then_makes_version_1_active(tmp_path: Path) -> None:
    env = build(tmp_path)
    doc_id = await create(env)
    assert doc_id.startswith("u-")
    assert env.acls.data[(T, DocumentId(doc_id))] == frozenset({GroupId("eng")})
    body = (await detail(env, doc_id)).json()
    assert body["active_version"] == 1 and body["searchable"] and not body["pending"]
    assert body["groups"] == ["eng"]


async def test_create_validates_input(tmp_path: Path) -> None:
    env = build(tmp_path)
    r = await env.client.post(
        "/admin/documents",
        json={"tenant_id": "t1", "title": "x", "text": "", "groups": []},
        headers=H,
    )
    assert r.status_code == 422
    assert env.bus.events == []


async def test_new_version_replaces_the_old_one(tmp_path: Path) -> None:
    env = build(tmp_path)
    doc_id = await create(env)
    r = await env.client.post(
        f"/admin/documents/{doc_id}/versions",
        json={"tenant_id": "t1", "title": "Doc", "text": "launch code BRAVO"},
        headers=H,
    )
    assert r.status_code == 202 and r.json()["version"] == 2
    assert (await detail(env, doc_id)).json()["active_version"] == 2
    hits = await env.vectors.search(CTX, (0.5,) * 8, 10)
    assert {h.version for h in hits} == {2}  # version 1 chunks were cleaned up


async def test_new_version_of_unknown_document_is_404_and_publishes_nothing(
    tmp_path: Path,
) -> None:
    env = build(tmp_path)
    r = await env.client.post(
        "/admin/documents/u-nope/versions",
        json={"tenant_id": "t1", "title": "Doc", "text": "x"},
        headers=H,
    )
    assert r.status_code == 404 and env.bus.events == []


async def test_delete_hides_the_document_and_a_new_version_revives_it(tmp_path: Path) -> None:
    env = build(tmp_path)
    doc_id = await create(env)
    r = await env.client.delete(f"/admin/documents/{doc_id}", params={"tenant": "t1"}, headers=H)
    assert r.status_code == 202 and r.json()["version"] == 2
    gone = (await detail(env, doc_id)).json()
    assert gone["status"] == "deleted" and not gone["searchable"]

    await env.client.post(
        f"/admin/documents/{doc_id}/versions",
        json={"tenant_id": "t1", "title": "Doc", "text": "back again"},
        headers=H,
    )
    back = (await detail(env, doc_id)).json()
    assert back["searchable"] and back["active_version"] == 3


async def test_out_of_order_old_version_loses(tmp_path: Path) -> None:
    env = build(tmp_path)
    doc_id = await create(env)
    r = await simulate(env, doc_id, "out_of_order")
    assert [p["version"] for p in r.json()["published"]] == [3, 2]
    body = (await detail(env, doc_id)).json()
    assert body["active_version"] == 3 and body["latest_seen_version"] == 3
    hits = await env.vectors.search(CTX, (0.5,) * 8, 10)
    assert {h.version for h in hits} == {3}  # the stale version never reached the index


async def test_late_update_after_delete_cannot_resurrect(tmp_path: Path) -> None:
    env = build(tmp_path)
    doc_id = await create(env)
    await simulate(env, doc_id, "late_update_after_delete")
    body = (await detail(env, doc_id)).json()
    assert body["status"] == DocStatus.DELETED.value and not body["searchable"]
    hits = await env.vectors.search(CTX, (0.5,) * 8, 10)
    assert {h.version for h in hits} == {1, 2}  # version 2 chunks are orphans: written, never served


async def test_slow_update_keeps_the_old_version_serving_until_it_lands(tmp_path: Path) -> None:
    env = build(tmp_path)
    doc_id = await create(env)
    await simulate(env, doc_id, "slow_update", delay_seconds=0.5)
    during = (await detail(env, doc_id)).json()
    assert during["pending"] and during["active_version"] == 1 and during["searchable"]
    assert during["latest_seen_version"] == 2
    await asyncio.sleep(1.0)
    after = (await detail(env, doc_id)).json()
    assert after["active_version"] == 2 and not after["pending"]


async def test_bus_down_is_503(tmp_path: Path) -> None:
    env = build(tmp_path)
    env.bus.down = True
    r = await env.client.post(
        "/admin/documents",
        json={"tenant_id": "t1", "title": "Doc", "text": "x", "groups": []},
        headers=H,
    )
    assert r.status_code == 503 and env.bus.events == []


async def test_detail_is_tenant_scoped(tmp_path: Path) -> None:
    env = build(tmp_path)
    doc_id = await create(env)
    assert (await detail(env, doc_id, tenant="t2")).status_code == 404


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("POST", "/admin/documents", {"tenant_id": "t1", "title": "t", "text": "x", "groups": []}),
        ("DELETE", "/admin/documents/x?tenant=t1", None),
        (
            "POST",
            "/admin/simulate",
            {
                "tenant_id": "t1",
                "document_id": "x",
                "scenario": "slow_update",
                "title": "t",
                "text": "x",
            },
        ),
    ],
)
async def test_lifecycle_routes_need_the_admin_key(
    tmp_path: Path, method: str, url: str, body: dict[str, Any] | None
) -> None:
    env = build(tmp_path)
    r = await env.client.request(method, url, json=body)
    assert r.status_code == 401


    