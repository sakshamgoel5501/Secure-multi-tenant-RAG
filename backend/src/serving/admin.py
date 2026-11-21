import asyncio
import json
import logging
import re
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from domain.models import (
    DocStatus,
    DocumentEvent,
    DocumentId,
    DocumentState,
    GroupId,
    Operation,
    TenantId,
)
from domain.ops_ports import (
    AclAdmin,
    AuditEntry,
    AuditLog,
    DeadLetterInspector,
    EventPublisher,
    StateScanner,
)
from domain.ports import DocStateStore
from eval.gate import check_gate
from ingestion.purge import Footprint, Purger
from serving.admin_auth import Principal, admin_identity

log = logging.getLogger("rag.admin")

MIN_KEY_CHARS = 32
MAX_TEXT = 20_000
_ID = re.compile(r"^[\w-]{1,64}$")


class AclUpdate(BaseModel):
    tenant_id: str = Field(min_length=1)
    groups: list[str] = Field(max_length=50)  # an empty list means "nobody", a full revocation


class NewDocument(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    groups: list[str] = Field(max_length=50)


class NewVersion(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=MAX_TEXT)


class Simulation(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    document_id: str = Field(min_length=1, max_length=64)
    scenario: Literal["out_of_order", "late_update_after_delete", "slow_update"]
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    delay_seconds: float = Field(default=5.0, ge=0.5, le=30.0)


def admin_key_from_env(env: Mapping[str, str]) -> str | None:
    """The key signs and verifies admin tokens. None means the admin API stays unmounted.
    Enabling it without a strong key is an error, so a misconfigured server never starts open."""
    if env.get("RAG_ADMIN") != "1":
        return None
    key = env.get("RAG_ADMIN_KEY", "")
    if len(key) < MIN_KEY_CHARS:
        raise SystemExit(f"RAG_ADMIN=1 needs RAG_ADMIN_KEY of at least {MIN_KEY_CHARS} characters")
    return key


def _read_json(path: Path) -> dict[str, float] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _check_id(value: str) -> None:
    if not _ID.match(value):
        raise HTTPException(status_code=400, detail="invalid id")


def _describe(state: DocumentState, groups: frozenset[GroupId]) -> dict[str, Any]:
    # "pending": a newer version has been announced but is not live yet (the old one still serves).
    pending = state.status is DocStatus.ACTIVE and (
        state.active_version is None or state.latest_seen_version > state.active_version
    )
    return {
        "document_id": str(state.document_id),
        "tenant": str(state.tenant_id),
        "status": state.status.value,
        "active_version": state.active_version,
        "latest_seen_version": state.latest_seen_version,
        "pending": pending,
        "searchable": state.is_searchable,
        "groups": sorted(str(g) for g in groups),
    }


def _footprint_json(f: Footprint) -> dict[str, Any]:
    return {
        "state": f.status,
        "has_acl": f.has_acl,
        "chunks": {name: {str(v): n for v, n in vs.items()} for name, vs in f.chunks.items()},
        "events": f.events,
        "content_left": f.content_left,
    }


def create_admin_router(
    states: DocStateStore,
    scanner: StateScanner,
    acls: AclAdmin,
    dlq: DeadLetterInspector,
    *,
    admin_key: str,
    data_dir: Path,
    audit: AuditLog,
    publisher: EventPublisher | None = None,
    purger: Purger | None = None,
) -> APIRouter:
    who = Depends(admin_identity(admin_key))
    router = APIRouter(prefix="/admin")
    background: set[asyncio.Task[None]] = set()

    async def deny(p: Principal, tenant: str | None, action: str, target: str) -> NoReturn:
        try:
            await audit.record(AuditEntry(p.actor, p.role, tenant, f"denied:{action}", target))
        except Exception:
            log.exception("audit write failed while recording a denial")
        raise HTTPException(status_code=403, detail="outside your admin scope")

    async def authorize(p: Principal, tenant: str, action: str, target: str = "") -> None:
        _check_id(tenant)
        if not p.can_manage(tenant):
            await deny(p, tenant, action, target)

    async def platform_only(p: Principal, action: str) -> None:
        if not p.platform:
            await deny(p, None, action, "")

    async def record(
        p: Principal, tenant: str, action: str, target: str, detail: dict[str, Any] | None = None
    ) -> None:
        """No audit, no action: if this fails, the caller must not make the change."""
        try:
            await audit.record(AuditEntry(p.actor, p.role, tenant, action, target, detail or {}))
        except Exception as exc:
            log.warning("audit write failed: %r", exc)
            raise HTTPException(
                status_code=503, detail="audit log unavailable; no change was made"
            ) from exc

    @router.get("/me")
    async def me(p: Principal = who) -> dict[str, Any]:
        return {"actor": p.actor, "role": p.role, "tenant": p.tenant}

    @router.get("/capabilities")
    async def capabilities(p: Principal = who) -> dict[str, bool]:
        return {"lifecycle": publisher is not None, "purge": purger is not None}

    @router.get("/tenants")
    async def tenants(p: Principal = who) -> dict[str, list[str]]:
        if p.platform:
            return {"tenants": [str(t) for t in await scanner.list_tenants()]}
        return {"tenants": [p.tenant] if p.tenant else []}

    @router.get("/documents")
    async def documents(
        tenant: str, limit: Annotated[int, Query(ge=1, le=1000)] = 200, p: Principal = who
    ) -> dict[str, Any]:
        await authorize(p, tenant, "documents.list")
        tenant_id = TenantId(tenant)
        found = await scanner.list_states(tenant_id)
        groups = await acls.list_acls(tenant_id)
        return {
            "tenant": tenant,
            "total": len(found),
            "documents": [
                {
                    "document_id": str(s.document_id),
                    "status": s.status.value,
                    "active_version": s.active_version,
                    "latest_seen_version": s.latest_seen_version,
                    "groups": sorted(str(g) for g in groups.get(s.document_id, frozenset())),
                }
                for s in found[:limit]
            ],
        }

    @router.put("/documents/{document_id}/acl")
    async def set_acl(document_id: str, body: AclUpdate, p: Principal = who) -> dict[str, Any]:
        await authorize(p, body.tenant_id, "acl.set", document_id)
        _check_id(document_id)
        tenant_id, doc_id = TenantId(body.tenant_id), DocumentId(document_id)
        if await states.get(tenant_id, doc_id) is None:
            raise HTTPException(status_code=404, detail="unknown document")
        before = (await acls.list_acls(tenant_id)).get(doc_id, frozenset())
        await record(
            p, body.tenant_id, "acl.set", document_id,
            {"before": sorted(str(g) for g in before), "after": sorted(body.groups)},
        )  # fmt: skip
        epoch = await acls.set_acl(tenant_id, doc_id, [GroupId(g) for g in body.groups])
        return {"epoch": epoch, "groups": sorted(body.groups)}

    @router.get("/eval")
    async def evaluation(p: Principal = who) -> dict[str, Any]:
        await platform_only(p, "eval.read")
        report = _read_json(data_dir / "eval_report.json")
        if report is None:
            raise HTTPException(status_code=404, detail="no report yet: run `rag eval`")
        baseline = _read_json(data_dir / "baseline.json")
        failures = check_gate(report, baseline) if baseline is not None else None
        return {"report": report, "baseline": baseline, "gate_failures": failures}

    @router.get("/dlq")
    async def dead_letters(p: Principal = who) -> dict[str, Any]:
        await platform_only(p, "dlq.read")
        try:
            return {"pending": await dlq.pending_count(), "entries": (await dlq.dlq_entries())[-50:]}
        except Exception as exc:
            raise HTTPException(status_code=503, detail="event bus unavailable") from exc

    @router.get("/audit")
    async def audit_entries(
        tenant: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        p: Principal = who,
    ) -> dict[str, Any]:
        if tenant is not None:
            await authorize(p, tenant, "audit.read")
        elif not p.platform:
            tenant = p.tenant  # a tenant admin only ever sees their own tenant
        rows = await audit.list_entries(tenant, limit)
        return {
            "entries": [
                {
                    "at": e.at, "actor": e.actor, "role": e.role, "tenant": e.tenant,
                    "action": e.action, "target": e.target, "detail": e.detail,
                }
                for e in rows
            ]
        }  # fmt: skip

    if purger is not None:
        eraser = purger

        async def known(tenant: str, document_id: str) -> tuple[TenantId, DocumentId]:
            _check_id(document_id)
            t, d = TenantId(tenant), DocumentId(document_id)
            if await states.get(t, d) is None:
                raise HTTPException(status_code=404, detail="unknown document")
            return t, d

        @router.get("/documents/{document_id}/footprint")
        async def footprint(document_id: str, tenant: str, p: Principal = who) -> dict[str, Any]:
            await authorize(p, tenant, "document.footprint", document_id)
            t, d = await known(tenant, document_id)
            try:
                return _footprint_json(await eraser.footprint(t, d))
            except Exception as exc:
                log.warning("footprint failed: %r", exc)
                raise HTTPException(status_code=503, detail="a backing store is unavailable") from exc

        @router.post("/documents/{document_id}/purge")
        async def purge_document(document_id: str, tenant: str, p: Principal = who) -> dict[str, Any]:
            await authorize(p, tenant, "document.purge", document_id)
            t, d = await known(tenant, document_id)
            await record(p, tenant, "document.purge", document_id)
            try:
                report = await eraser.purge(t, d)
            except Exception as exc:
                log.warning("purge failed: %r", exc)
                raise HTTPException(
                    status_code=503,
                    detail="a backing store is unavailable; the purge is safe to retry",
                ) from exc
            return {
                "chunks_deleted": report.chunks_deleted,
                "events_deleted": report.events_deleted,
                "acl_removed": report.acl_removed,
                "epoch": report.epoch,
                "after": _footprint_json(report.after),
            }

    if publisher is None:
        return router
    bus = publisher

    async def publish(event: DocumentEvent) -> None:
        try:
            await bus.publish(event)
        except Exception as exc:
            log.warning("publish failed: %r", exc)
            raise HTTPException(status_code=503, detail="event bus unavailable") from exc

    async def existing(tenant: str, document_id: str) -> DocumentState:
        _check_id(tenant)
        _check_id(document_id)
        state = await states.get(TenantId(tenant), DocumentId(document_id))
        if state is None:
            raise HTTPException(status_code=404, detail="unknown document")
        return state

    @router.post("/documents", status_code=201)
    async def create_document(body: NewDocument, p: Principal = who) -> dict[str, Any]:
        await authorize(p, body.tenant_id, "document.create")
        tenant_id = TenantId(body.tenant_id)
        doc_id = DocumentId(f"u-{uuid.uuid4().hex[:8]}")  # "u-": uploaded, not in the eval corpus
        await record(
            p, body.tenant_id, "document.create", str(doc_id),
            {"title": body.title, "groups": sorted(body.groups), "chars": len(body.text)},
        )  # fmt: skip
        # ACL first, so the document is never searchable without its permissions.
        epoch = await acls.set_acl(tenant_id, doc_id, [GroupId(g) for g in body.groups])
        await publish(DocumentEvent(Operation.UPSERT, tenant_id, doc_id, 1, body.title, body.text))
        return {"document_id": str(doc_id), "version": 1, "epoch": epoch}

    @router.get("/documents/{document_id}")
    async def document_detail(document_id: str, tenant: str, p: Principal = who) -> dict[str, Any]:
        await authorize(p, tenant, "document.read", document_id)
        state = await existing(tenant, document_id)
        groups = (await acls.list_acls(TenantId(tenant))).get(DocumentId(document_id), frozenset())
        return _describe(state, groups)

    @router.post("/documents/{document_id}/versions", status_code=202)
    async def new_version(document_id: str, body: NewVersion, p: Principal = who) -> dict[str, Any]:
        await authorize(p, body.tenant_id, "document.version", document_id)
        state = await existing(body.tenant_id, document_id)
        version = state.latest_seen_version + 1  # also revives a deleted document
        tenant_id, doc_id = TenantId(body.tenant_id), DocumentId(document_id)
        await record(
            p, body.tenant_id, "document.version", document_id,
            {"version": version, "title": body.title, "chars": len(body.text)},
        )  # fmt: skip
        await publish(DocumentEvent(Operation.UPSERT, tenant_id, doc_id, version, body.title, body.text))
        await states.record_seen(tenant_id, doc_id, version)  # monotonic; makes "pending" visible
        return {"document_id": document_id, "version": version}

    @router.delete("/documents/{document_id}", status_code=202)
    async def delete_document(document_id: str, tenant: str, p: Principal = who) -> dict[str, Any]:
        await authorize(p, tenant, "document.delete", document_id)
        state = await existing(tenant, document_id)
        version = state.latest_seen_version + 1
        await record(p, tenant, "document.delete", document_id, {"version": version})
        await publish(
            DocumentEvent(Operation.DELETE, TenantId(tenant), DocumentId(document_id), version)
        )
        return {"document_id": document_id, "version": version}

    @router.post("/simulate", status_code=202)
    async def simulate(body: Simulation, p: Principal = who) -> dict[str, Any]:
        """Publishes events the way a flaky bus would deliver them, so the guarantees can be watched."""
        await authorize(p, body.tenant_id, "simulate", body.document_id)
        state = await existing(body.tenant_id, body.document_id)
        await record(p, body.tenant_id, "simulate", body.document_id, {"scenario": body.scenario})
        tenant_id, doc_id = TenantId(body.tenant_id), DocumentId(body.document_id)
        base = state.latest_seen_version

        def upsert(version: int, text: str) -> DocumentEvent:
            return DocumentEvent(Operation.UPSERT, tenant_id, doc_id, version, body.title, text)

        if body.scenario == "out_of_order":
            await publish(upsert(base + 2, body.text))
            await publish(upsert(base + 1, f"STALE, must never be served: {body.text}"))
            sent = [("upsert", base + 2), ("upsert", base + 1)]
        elif body.scenario == "late_update_after_delete":
            await publish(DocumentEvent(Operation.DELETE, tenant_id, doc_id, base + 2))
            await publish(upsert(base + 1, body.text))
            sent = [("delete", base + 2), ("upsert", base + 1)]
        else:
            version = base + 1
            await states.record_seen(tenant_id, doc_id, version)
            event = upsert(version, body.text)

            async def later() -> None:
                try:
                    await asyncio.sleep(body.delay_seconds)
                    await bus.publish(event)
                except Exception:
                    log.exception("delayed publish failed")

            task = asyncio.create_task(later())
            background.add(task)
            task.add_done_callback(background.discard)
            sent = [("upsert", version)]

        return {
            "scenario": body.scenario,
            "published": [{"operation": op, "version": v} for op, v in sent],
        }

    return router



