import json
from collections.abc import Collection
from pathlib import Path

import httpx
from admin_tokens import admin_headers, admin_token
from fastapi import FastAPI

from adapters.memory_audit import InMemoryAuditLog
from adapters.memory_doc_state import InMemoryDocStateStore
from domain.models import DocStatus, DocumentId, DocumentState, GroupId, TenantId
from serving.admin import create_admin_router
from domain.ops_ports import AuditEntry

KEY = "k" * 32
T1, T2 = TenantId("t1"), TenantId("t2")
D1, D2 = DocumentId("d1"), DocumentId("d2")
PLATFORM = admin_headers(KEY)
ADMIN_T1 = admin_headers(KEY, "tenant_admin", "t1")


class Scanner:
    async def list_tenants(self) -> list[TenantId]:
        return [T1, T2]

    async def list_states(self, tenant_id: TenantId) -> list[DocumentState]:
        doc = D1 if tenant_id == T1 else D2
        return [DocumentState(doc, tenant_id, 1, 1, DocStatus.ACTIVE)]


class Acls:
    def __init__(self) -> None:
        self.data: dict[tuple[TenantId, DocumentId], frozenset[GroupId]] = {
            (T1, D1): frozenset({GroupId("eng")}),
            (T2, D2): frozenset({GroupId("eng")}),
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


class Bus:
    async def pending_count(self) -> int:
        return 0

    async def dlq_entries(self) -> list[dict[str, str]]:
        return []


async def build(tmp_path: Path) -> tuple[httpx.AsyncClient, Acls, InMemoryAuditLog]:
    state = InMemoryDocStateStore()
    await state.promote(T1, D1, 1)
    await state.promote(T2, D2, 1)
    acls, audit = Acls(), InMemoryAuditLog()
    app = FastAPI()
    app.include_router(
        create_admin_router(state, Scanner(), acls, Bus(), admin_key=KEY, data_dir=tmp_path, audit=audit)
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, acls, audit


async def test_user_tokens_and_bad_tokens_are_rejected(tmp_path: Path) -> None:
    c, _, _ = await build(tmp_path)
    bad = {
        "user audience": admin_token(KEY, aud="rag"),
        "wrong secret": admin_token("x" * 32),
        "expired": admin_token(KEY, exp_in=-10),
        "tenant admin without a tenant": admin_token(KEY, "tenant_admin"),
        "unknown role": admin_token(KEY, "superuser"),
    }
    for name, token in bad.items():
        r = await c.get("/admin/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, name
    assert (await c.get("/admin/me")).status_code == 401


async def test_me_reports_the_role(tmp_path: Path) -> None:
    c, _, _ = await build(tmp_path)
    assert (await c.get("/admin/me", headers=ADMIN_T1)).json() == {
        "actor": "tester", "role": "tenant_admin", "tenant": "t1",
    }  # fmt: skip


async def test_tenant_admin_manages_own_tenant_only(tmp_path: Path) -> None:
    c, _, audit = await build(tmp_path)
    own = await c.get("/admin/documents", params={"tenant": "t1"}, headers=ADMIN_T1)
    assert own.status_code == 200
    other = await c.get("/admin/documents", params={"tenant": "t2"}, headers=ADMIN_T1)
    assert other.status_code == 403
    assert audit.entries[-1].action == "denied:documents.list"
    assert (await c.get("/admin/documents", params={"tenant": "t2"}, headers=PLATFORM)).status_code == 403


async def test_tenants_list_is_scoped(tmp_path: Path) -> None:
    c, _, _ = await build(tmp_path)
    assert (await c.get("/admin/tenants", headers=ADMIN_T1)).json() == {"tenants": ["t1"]}
    assert (await c.get("/admin/tenants", headers=PLATFORM)).json() == {"tenants": ["t1", "t2"]}


async def test_acl_change_is_audited_with_before_and_after(tmp_path: Path) -> None:
    c, acls, audit = await build(tmp_path)
    r = await c.put(
        "/admin/documents/d1/acl", json={"tenant_id": "t1", "groups": ["hr"]}, headers=ADMIN_T1
    )
    assert r.status_code == 200
    entry = audit.entries[-1]
    assert (entry.action, entry.role, entry.tenant, entry.target) == ("acl.set", "tenant_admin", "t1", "d1")
    assert entry.detail == {"before": ["eng"], "after": ["hr"]}
    assert acls.data[(T1, D1)] == frozenset({GroupId("hr")})


async def test_cross_tenant_acl_change_is_denied_and_changes_nothing(tmp_path: Path) -> None:
    c, acls, audit = await build(tmp_path)
    r = await c.put(
        "/admin/documents/d2/acl", json={"tenant_id": "t2", "groups": []}, headers=ADMIN_T1
    )
    assert r.status_code == 403
    assert acls.data[(T2, D2)] == frozenset({GroupId("eng")}) and acls.epoch == 0
    assert audit.entries[-1].action == "denied:acl.set"


async def test_no_audit_no_action(tmp_path: Path) -> None:
    c, acls, audit = await build(tmp_path)
    audit.fail = True
    r = await c.put(
        "/admin/documents/d1/acl", json={"tenant_id": "t1", "groups": ["hr"]}, headers=ADMIN_T1
    )
    assert r.status_code == 503
    assert acls.data[(T1, D1)] == frozenset({GroupId("eng")})  # the change was not made


async def test_a_denial_is_still_a_denial_when_the_audit_store_is_down(tmp_path: Path) -> None:
    c, _, audit = await build(tmp_path)
    audit.fail = True
    r = await c.get("/admin/documents", params={"tenant": "t2"}, headers=ADMIN_T1)
    assert r.status_code == 403


async def test_eval_and_queue_are_platform_only(tmp_path: Path) -> None:
    (tmp_path / "eval_report.json").write_text(json.dumps({"recall_at_5": 1.0}))
    c, _, _ = await build(tmp_path)
    assert (await c.get("/admin/eval", headers=ADMIN_T1)).status_code == 403
    assert (await c.get("/admin/dlq", headers=ADMIN_T1)).status_code == 403
    assert (await c.get("/admin/eval", headers=PLATFORM)).status_code == 200
    assert (await c.get("/admin/dlq", headers=PLATFORM)).status_code == 200


async def test_audit_view_is_scoped(tmp_path: Path) -> None:
    c, _, audit = await build(tmp_path)
    for tenant, doc in (("t1", "d1"), ("t2", "d2")):
        await c.put(
            f"/admin/documents/{doc}/acl", json={"tenant_id": tenant, "groups": []},
            headers=admin_headers(KEY, "tenant_admin", tenant),
        )  # fmt: skip
    await audit.record(AuditEntry("root", "platform_admin", "t1", "user.create", "bob"))
    own = (await c.get("/admin/audit", headers=ADMIN_T1)).json()["entries"]
    assert {e["tenant"] for e in own} == {"t1"}
    platform = (await c.get("/admin/audit", headers=PLATFORM)).json()["entries"]
    assert [e["action"] for e in platform] == ["user.create"]  # accounts, never tenant activity
    assert (await c.get("/admin/audit", params={"tenant": "t2"}, headers=ADMIN_T1)).status_code == 403

    
    