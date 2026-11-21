import json
from collections.abc import Collection
from pathlib import Path

import httpx
import pytest
from admin_tokens import admin_headers
from fastapi import FastAPI

from adapters.memory_audit import InMemoryAuditLog
from adapters.memory_doc_state import InMemoryDocStateStore
from domain.models import DocStatus, DocumentId, DocumentState, GroupId, TenantId
from serving.admin import admin_key_from_env, create_admin_router

KEY = "k" * 32
H = admin_headers(KEY)
T = TenantId("t1")
D = DocumentId("d1")


class Scanner:
    def __init__(self, states: list[DocumentState]) -> None:
        self._states = states

    async def list_tenants(self) -> list[TenantId]:
        return sorted({s.tenant_id for s in self._states})

    async def list_states(self, tenant_id: TenantId) -> list[DocumentState]:
        return [s for s in self._states if s.tenant_id == tenant_id]


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


class Bus:
    def __init__(self, down: bool = False) -> None:
        self.down = down

    async def pending_count(self) -> int:
        if self.down:
            raise ConnectionError("redis down")
        return 2

    async def dlq_entries(self) -> list[dict[str, str]]:
        return [{"original_id": "1-0", "error": "boom", "deliveries": "5"}]


async def build(
    tmp_path: Path, bus: Bus | None = None
) -> tuple[httpx.AsyncClient, Acls]:
    state = InMemoryDocStateStore()
    await state.promote(T, D, 1)
    scanner = Scanner(
        [
            DocumentState(D, T, 1, 1, DocStatus.ACTIVE),
            DocumentState(DocumentId("x"), TenantId("t2"), 1, 1, DocStatus.ACTIVE),
        ]
    )
    acls = Acls()
    acls.data[(T, D)] = frozenset({GroupId("eng"), GroupId("hr")})
    app = FastAPI()
    app.include_router(
        create_admin_router(
            state, scanner, acls, bus or Bus(), admin_key=KEY, data_dir=tmp_path, audit=InMemoryAuditLog(),
        )
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, acls


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nope"}])
async def test_missing_or_wrong_key_is_401(tmp_path: Path, headers: dict[str, str]) -> None:
    client, _ = await build(tmp_path)
    assert (await client.get("/admin/tenants", headers=headers)).status_code == 401


async def test_documents_list_state_with_groups(tmp_path: Path) -> None:
    client, _ = await build(tmp_path)
    r = await client.get("/admin/documents", params={"tenant": "t1"}, headers=H)
    [doc] = r.json()["documents"]
    assert doc["document_id"] == "d1"
    assert doc["active_version"] == 1 and doc["status"] == "active"
    assert doc["groups"] == ["eng", "hr"]


async def test_documents_are_tenant_scoped(tmp_path: Path) -> None:
    client, _ = await build(tmp_path)
    r = await client.get("/admin/documents", params={"tenant": "t2"}, headers=H)
    assert [d["document_id"] for d in r.json()["documents"]] == ["x"]


async def test_set_acl_changes_groups_and_returns_epoch(tmp_path: Path) -> None:
    client, acls = await build(tmp_path)
    r = await client.put(
        "/admin/documents/d1/acl", json={"tenant_id": "t1", "groups": ["hr"]}, headers=H
    )
    assert r.status_code == 200 and r.json() == {"epoch": 1, "groups": ["hr"]}
    assert acls.data[(T, D)] == frozenset({GroupId("hr")})


async def test_set_acl_on_unknown_document_is_404(tmp_path: Path) -> None:
    client, acls = await build(tmp_path)
    r = await client.put(
        "/admin/documents/nope/acl", json={"tenant_id": "t1", "groups": []}, headers=H
    )
    assert r.status_code == 404
    assert acls.epoch == 0  # nothing was written


async def test_eval_is_404_without_a_report(tmp_path: Path) -> None:
    client, _ = await build(tmp_path)
    assert (await client.get("/admin/eval", headers=H)).status_code == 404


async def test_eval_reports_gate_failures(tmp_path: Path) -> None:
    (tmp_path / "eval_report.json").write_text(json.dumps({"recall_at_5": 0.5}))
    (tmp_path / "baseline.json").write_text(json.dumps({"recall_at_5": 0.95}))
    client, _ = await build(tmp_path)
    body = (await client.get("/admin/eval", headers=H)).json()
    assert body["report"] == {"recall_at_5": 0.5}
    assert "recall_at_5" in body["gate_failures"][0]


async def test_dlq_lists_entries(tmp_path: Path) -> None:
    client, _ = await build(tmp_path)
    body = (await client.get("/admin/dlq", headers=H)).json()
    assert body["pending"] == 2 and body["entries"][0]["error"] == "boom"


async def test_dlq_with_bus_down_is_503(tmp_path: Path) -> None:
    client, _ = await build(tmp_path, Bus(down=True))
    assert (await client.get("/admin/dlq", headers=H)).status_code == 503


def test_admin_is_disabled_by_default() -> None:
    assert admin_key_from_env({}) is None


def test_enabling_admin_without_a_key_refuses_to_start() -> None:
    with pytest.raises(SystemExit):
        admin_key_from_env({"RAG_ADMIN": "1"})


def test_a_short_key_is_rejected() -> None:
    with pytest.raises(SystemExit):
        admin_key_from_env({"RAG_ADMIN": "1", "RAG_ADMIN_KEY": "short"})


def test_a_strong_key_is_returned() -> None:
    assert admin_key_from_env({"RAG_ADMIN": "1", "RAG_ADMIN_KEY": KEY}) == KEY




    