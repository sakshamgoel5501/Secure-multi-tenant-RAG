import asyncio
import hmac
import json
import logging
import re
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
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
from domain.ops_ports import AclAdmin, DeadLetterInspector, EventPublisher, StateScanner
from domain.ports import DocStateStore
from eval.gate import check_gate

log = logging.getLogger("rag.admin")

MIN_KEY_CHARS = 16
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
    """None means the admin API stays unmounted. Enabling it without a strong key is an error,
    so a misconfigured server never starts with an open admin surface."""
    if env.get("RAG_ADMIN") != "1":
        return None
    key = env.get("RAG_ADMIN_KEY", "")
    if len(key) < MIN_KEY_CHARS:
        raise SystemExit(f"RAG_ADMIN=1 needs RAG_ADMIN_KEY of at least {MIN_KEY_CHARS} characters")
    return key


def require_admin(key: str) -> Callable[..., None]:
    def check(x_admin_key: Annotated[str | None, Header()] = None) -> None:
        if x_admin_key is None or not hmac.compare_digest(x_admin_key.encode(), key.encode()):
            raise HTTPException(status_code=403, detail="admin key required")

    return check


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


def create_admin_router(
    states: DocStateStore,
    scanner: StateScanner,
    acls: AclAdmin,
    dlq: DeadLetterInspector,
    *,
    admin_key: str,
    data_dir: Path,
    publisher: EventPublisher | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin(admin_key))])
    background: set[asyncio.Task[None]] = set()

    @router.get("/tenants")
    async def tenants() -> dict[str, list[str]]:
        return {"tenants": [str(t) for t in await scanner.list_tenants()]}

    @router.get("/documents")
    async def documents(
        tenant: str, limit: Annotated[int, Query(ge=1, le=1000)] = 200
    ) -> dict[str, Any]:
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
    async def set_acl(document_id: str, body: AclUpdate) -> dict[str, Any]:
        tenant_id = TenantId(body.tenant_id)
        doc_id = DocumentId(document_id)
        if await states.get(tenant_id, doc_id) is None:
            raise HTTPException(status_code=404, detail="unknown document")
        epoch = await acls.set_acl(tenant_id, doc_id, [GroupId(g) for g in body.groups])
        return {"epoch": epoch, "groups": sorted(body.groups)}

    @router.get("/eval")
    async def evaluation() -> dict[str, Any]:
        report = _read_json(data_dir / "eval_report.json")
        if report is None:
            raise HTTPException(status_code=404, detail="no report yet: run `rag eval`")
        baseline = _read_json(data_dir / "baseline.json")
        failures = check_gate(report, baseline) if baseline is not None else None
        return {"report": report, "baseline": baseline, "gate_failures": failures}

    @router.get("/dlq")
    async def dead_letters() -> dict[str, Any]:
        try:
            return {"pending": await dlq.pending_count(), "entries": (await dlq.dlq_entries())[-50:]}
        except Exception as exc:
            raise HTTPException(status_code=503, detail="event bus unavailable") from exc

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
    async def create_document(body: NewDocument) -> dict[str, Any]:
        _check_id(body.tenant_id)
        tenant_id = TenantId(body.tenant_id)
        doc_id = DocumentId(f"u-{uuid.uuid4().hex[:8]}")  # "u-": uploaded, not in the eval corpus
        # ACL first, so the document is never searchable without its permissions.
        epoch = await acls.set_acl(tenant_id, doc_id, [GroupId(g) for g in body.groups])
        await publish(DocumentEvent(Operation.UPSERT, tenant_id, doc_id, 1, body.title, body.text))
        return {"document_id": str(doc_id), "version": 1, "epoch": epoch}

    @router.get("/documents/{document_id}")
    async def document_detail(document_id: str, tenant: str) -> dict[str, Any]:
        state = await existing(tenant, document_id)
        groups = (await acls.list_acls(TenantId(tenant))).get(DocumentId(document_id), frozenset())
        return _describe(state, groups)

    @router.post("/documents/{document_id}/versions", status_code=202)
    async def new_version(document_id: str, body: NewVersion) -> dict[str, Any]:
        state = await existing(body.tenant_id, document_id)
        version = state.latest_seen_version + 1  # also revives a deleted document
        tenant_id, doc_id = TenantId(body.tenant_id), DocumentId(document_id)
        await publish(DocumentEvent(Operation.UPSERT, tenant_id, doc_id, version, body.title, body.text))
        await states.record_seen(tenant_id, doc_id, version)  # monotonic; makes "pending" visible
        return {"document_id": document_id, "version": version}

    @router.delete("/documents/{document_id}", status_code=202)
    async def delete_document(document_id: str, tenant: str) -> dict[str, Any]:
        state = await existing(tenant, document_id)
        version = state.latest_seen_version + 1
        await publish(
            DocumentEvent(Operation.DELETE, TenantId(tenant), DocumentId(document_id), version)
        )
        return {"document_id": document_id, "version": version}

    @router.post("/simulate", status_code=202)
    async def simulate(body: Simulation) -> dict[str, Any]:
        """Publishes events the way a flaky bus would deliver them, so the guarantees can be watched."""
        state = await existing(body.tenant_id, body.document_id)
        tenant_id, doc_id = TenantId(body.tenant_id), DocumentId(body.document_id)
        base = state.latest_seen_version

        def upsert(version: int, text: str) -> DocumentEvent:
            return DocumentEvent(Operation.UPSERT, tenant_id, doc_id, version, body.title, text)

        if body.scenario == "out_of_order":
            # Version base+2 arrives first, then base+1. The late one must lose.
            await publish(upsert(base + 2, body.text))
            await publish(upsert(base + 1, f"STALE, must never be served: {body.text}"))
            sent = [("upsert", base + 2), ("upsert", base + 1)]
        elif body.scenario == "late_update_after_delete":
            # A delete at base+2 arrives, then an update from before the delete (base+1).
            await publish(DocumentEvent(Operation.DELETE, tenant_id, doc_id, base + 2))
            await publish(upsert(base + 1, body.text))
            sent = [("delete", base + 2), ("upsert", base + 1)]
        else:
            # The version is announced now, but the work arrives later. The old one keeps serving.
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


