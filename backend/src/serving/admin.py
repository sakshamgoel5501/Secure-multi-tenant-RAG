import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal, NoReturn

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from domain.errors import FileRejected

from domain.models import (
    DocStatus,
    DocumentEvent,
    DocumentId,
    DocumentState,
    GroupId,
    Operation,
    TenantId,
    SearchHit, 
    SecurityContext, 
    UserId,
)
from domain.ops_ports import (
    AclAdmin,
    AuditEntry,
    AuditLog,
    DeadLetterInspector,
    EventPublisher,
    StateScanner,
    AccountStore,
    BlobStore,
)
from domain.ports import DocStateStore, EpochSource, FileParser
from eval.gate import check_gate
from ingestion.purge import Footprint, Purger
from serving.admin_auth import Principal, admin_identity


log = logging.getLogger("rag.admin")

MIN_KEY_CHARS = 32
MAX_TEXT = 20_000
READ_AUDIT_WINDOW = 60.0  # seconds: the same read by the same person is logged once per window
_ID = re.compile(r"^[\w-]{1,64}$")
PARSE_TIMEOUT = 20.0
MAX_FILE_BYTES = 10_000_000

PLATFORM_AUDIT_PREFIXES = ("user.", "auth.")  # all a platform administrator sees of the audit log
Searcher = Callable[[SecurityContext, str, int], Awaitable[list[SearchHit]]]


class Probe(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    group: str = Field(min_length=1, max_length=64)
    query: str = Field(min_length=1, max_length=500)


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
        "blobs": f.blobs,
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
    accounts: AccountStore | None = None, 
    searcher: Searcher | None = None, 
    epochs: EpochSource | None = None,
    blobs: BlobStore | None = None, 
    parser: FileParser | None = None, 
    max_file_bytes: int = MAX_FILE_BYTES,
) -> APIRouter:
    who = Depends(admin_identity(admin_key, accounts))
    router = APIRouter(prefix="/admin")
    background: set[asyncio.Task[None]] = set()
    last_read: dict[tuple[str, str, str], float] = {}

    async def deny(
        p: Principal, tenant: str | None, action: str, target: str,
        message: str = "outside your admin scope",
    ) -> NoReturn:  # fmt: skip
        try:
            await audit.record(AuditEntry(p.actor, p.role, tenant, f"denied:{action}", target))
        except Exception:
            log.exception("audit write failed while recording a denial")
        raise HTTPException(status_code=403, detail=message)

    async def authorize(p: Principal, tenant: str, action: str, target: str = "") -> None:
        _check_id(tenant)
        if p.platform:
            await deny(
                p, tenant, action, target,
                "platform administrators manage accounts and the platform, not tenant data",
            )  # fmt: skip
        if not p.can_manage(tenant):
            await deny(p, tenant, action, target)

    async def authorize_doc(p: Principal, tenant: str, action: str, document_id: str) -> None:
        """Tenant reach, plus: a group admin may only touch documents their group can read.
        A document they can't see and a document that doesn't exist look the same (403)."""
        await authorize(p, tenant, action, document_id)
        _check_id(document_id)
        if p.group_scoped:
            groups = (await acls.list_acls(TenantId(tenant))).get(DocumentId(document_id), frozenset())
            if p.group is None or GroupId(p.group) not in groups:
                await deny(p, tenant, action, document_id)

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

    async def note_read(p: Principal, tenant: str | None, action: str, target: str = "") -> None:
        """Best-effort and throttled: polling pages would otherwise flood the log."""
        key = (p.actor, action, f"{tenant}:{target}")
        now = time.monotonic()
        previous = last_read.get(key)
        if previous is not None and now - previous < READ_AUDIT_WINDOW:
            return
        if len(last_read) > 2000:
            last_read.clear()
        last_read[key] = now
        try:
            await audit.record(AuditEntry(p.actor, p.role, tenant, f"read:{action}", target))
        except Exception:
            log.warning("read audit failed", exc_info=True)

    @router.get("/me")
    async def me(p: Principal = who) -> dict[str, Any]:
        return {"actor": p.actor, "role": p.role, "tenant": p.tenant}

    @router.get("/capabilities")
    async def capabilities(p: Principal = who) -> dict[str, bool]:
        return {
            "lifecycle": publisher is not None,
            "purge": purger is not None,
            "files": publisher is not None and blobs is not None and parser is not None,
        }

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
        if p.group_scoped and p.group is not None:
            mine = GroupId(p.group)
            found = [s for s in found if mine in groups.get(s.document_id, frozenset())]
        await note_read(p, tenant, "documents.list")
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
        await authorize_doc(p, body.tenant_id, "acl.set", document_id)
        if p.group_scoped and p.group not in body.groups:
            await deny(
                p, body.tenant_id, "acl.set", document_id,
                "keep your own group on the document; a tenant administrator can remove it",
            )  # fmt: skip
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
            pending = await dlq.pending_count()
            entries = (await dlq.dlq_entries())[-50:]
        except Exception as exc:
            raise HTTPException(status_code=503, detail="event bus unavailable") from exc
        await note_read(p, None, "dlq.read")
        # The raw event carries the document text. Managing is not reading, so it is dropped here.
        return {"pending": pending, "entries": [{k: v for k, v in e.items() if k != "data"} for e in entries]}

    @router.get("/audit")
    async def audit_entries(
        tenant: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        p: Principal = who,
    ) -> dict[str, Any]:
        if p.group_scoped:
            await deny(p, tenant or p.tenant, "audit.read", "", "group administrators cannot read the audit log")
        prefixes: tuple[str, ...] | None = None
        if p.platform:
            prefixes = PLATFORM_AUDIT_PREFIXES  # accounts and sign-ins only, never tenant activity
        elif tenant is not None:
            await authorize(p, tenant, "audit.read")
        else:
            tenant = p.tenant  # a tenant admin only ever sees their own tenant
        rows = await audit.list_entries(tenant, limit, prefixes=prefixes)
        await note_read(p, tenant, "audit.read")
        return {
            "entries": [
                {
                    "at": e.at, "actor": e.actor, "role": e.role, "tenant": e.tenant,
                    "action": e.action, "target": e.target, "detail": e.detail,
                }
                for e in rows
            ]
        }  # fmt: skip
    
    if searcher is not None and epochs is not None:
        search = searcher
        epoch_source = epochs

        @router.post("/documents/{document_id}/probe")
        async def probe(document_id: str, body: Probe, p: Principal = who) -> dict[str, Any]:
            """Would a member of `group` find this document? Runs the real retrieval path and answers
            with a yes/no and a version, never text. Only for documents the caller manages."""
            await authorize_doc(p, body.tenant_id, "document.probe", document_id)
            _check_id(body.group)
            ctx = SecurityContext(
                TenantId(body.tenant_id), UserId("probe"), frozenset({GroupId(body.group)}),
                await epoch_source.current_epoch(),
            )  # fmt: skip
            hits = [h for h in await search(ctx, body.query, 10) if h.document_id == document_id]
            await note_read(p, body.tenant_id, "document.probe", document_id)
            return {"found": bool(hits), "version": hits[0].version if hits else None}

    if purger is not None:
        eraser = purger

        async def known(tenant: str, document_id: str) -> tuple[TenantId, DocumentId]:
            t, d = TenantId(tenant), DocumentId(document_id)
            if await states.get(t, d) is None:
                raise HTTPException(status_code=404, detail="unknown document")
            return t, d

        @router.get("/documents/{document_id}/footprint")
        async def footprint(document_id: str, tenant: str, p: Principal = who) -> dict[str, Any]:
            await authorize_doc(p, tenant, "document.footprint", document_id)
            t, d = await known(tenant, document_id)
            try:
                fp = await eraser.footprint(t, d)
            except Exception as exc:  # noqa: BLE001
                log.warning("footprint failed: %r", exc)
                raise HTTPException(status_code=503, detail="a backing store is unavailable") from exc
            state = await states.get(t, d)
            live = state.active_version if state is not None and state.is_searchable else None
            result = _footprint_json(fp)
            result["live_version"] = live
            # Chunks no query can reach: any version other than the live one, or all of them if
            # the document isn't searchable. The scheduled cleanup removes them.
            result["unreachable"] = {
                name: {str(v): n for v, n in versions.items() if v != live}
                for name, versions in fp.chunks.items()
            }
            if blobs is not None:
                result["files"] = [
                    {"version": b.version, "kind": b.kind, "bytes": b.size}
                    for b in await blobs.list_blobs(t, d)
                ]
            await note_read(p, tenant, "document.footprint", document_id)
            return result

        @router.post("/documents/{document_id}/purge")
        async def purge_document(document_id: str, tenant: str, p: Principal = who) -> dict[str, Any]:
            await authorize_doc(p, tenant, "document.purge", document_id)
            if p.group_scoped:
                await deny(
                    p, tenant, "document.purge", document_id,
                    "only tenant or platform administrators can purge a document",
                )  # fmt: skip
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
                "blobs_deleted": report.blobs_deleted,
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

    def parse_groups(raw: str) -> list[str]:
        groups = sorted({g.strip() for g in raw.split(",") if g.strip()})
        if len(groups) > 50 or any(not _ID.match(g) for g in groups):
            raise HTTPException(status_code=422, detail="invalid groups")
        return groups

    async def keep_files(
        tenant: str, document_id: str, version: int, title: str, text: str, source: str, original: bytes | None
    ) -> None:
        if blobs is None:
            return
        t, d = TenantId(tenant), DocumentId(document_id)
        try:
            if original is not None:
                await blobs.put(t, d, version, "original", original)
            await blobs.put(t, d, version, "text", text.encode())
            await blobs.put(t, d, version, "meta", json.dumps({"title": title, "source": source}).encode())
        except Exception as exc:  # noqa: BLE001
            log.warning("file store write failed: %r", exc)
            raise HTTPException(status_code=503, detail="file store unavailable; no change was made") from exc

    async def make_document(
        p: Principal, tenant_id: str, title: str, text: str, groups: list[str], source: str, original: bytes | None
    ) -> dict[str, Any]:
        await authorize(p, tenant_id, "document.create")
        if p.group_scoped and p.group not in groups:
            await deny(
                p, tenant_id, "document.create", "",
                "a group administrator's documents must include their own group",
            )  # fmt: skip
        tid = TenantId(tenant_id)
        doc_id = DocumentId(f"u-{uuid.uuid4().hex[:8]}")  # "u-": uploaded, not in the eval corpus
        await record(
            p, tenant_id, "document.create", str(doc_id),
            {"title": title, "groups": sorted(groups), "chars": len(text), "source": source,
             "bytes": None if original is None else len(original)},
        )  # fmt: skip
        await keep_files(tenant_id, str(doc_id), 1, title, text, source, original)
        # ACL first, so the document is never searchable without its permissions.
        epoch = await acls.set_acl(tid, doc_id, [GroupId(g) for g in groups])
        await publish(DocumentEvent(Operation.UPSERT, tid, doc_id, 1, title, text))
        return {"document_id": str(doc_id), "version": 1, "epoch": epoch}

    async def make_version(
        p: Principal, tenant_id: str, document_id: str, title: str, text: str, source: str, original: bytes | None
    ) -> dict[str, Any]:
        await authorize_doc(p, tenant_id, "document.version", document_id)
        state = await existing(tenant_id, document_id)
        version = state.latest_seen_version + 1  # also revives a deleted document
        tid, doc_id = TenantId(tenant_id), DocumentId(document_id)
        await record(
            p, tenant_id, "document.version", document_id,
            {"version": version, "title": title, "chars": len(text), "source": source,
             "bytes": None if original is None else len(original)},
        )  # fmt: skip
        await keep_files(tenant_id, document_id, version, title, text, source, original)
        await publish(DocumentEvent(Operation.UPSERT, tid, doc_id, version, title, text))
        await states.record_seen(tid, doc_id, version)  # monotonic; makes "pending" visible
        return {"document_id": document_id, "version": version}

    @router.post("/documents", status_code=201)
    async def create_document(body: NewDocument, p: Principal = who) -> dict[str, Any]:
        return await make_document(p, body.tenant_id, body.title, body.text, body.groups, "paste", None)
    
    @router.get("/documents/{document_id}")
    async def document_detail(document_id: str, tenant: str, p: Principal = who) -> dict[str, Any]:
        await authorize_doc(p, tenant, "document.read", document_id)
        state = await existing(tenant, document_id)
        groups = (await acls.list_acls(TenantId(tenant))).get(DocumentId(document_id), frozenset())
        await note_read(p, tenant, "document.read", document_id)
        return _describe(state, groups)

    @router.post("/documents/{document_id}/versions", status_code=202)
    async def new_version(document_id: str, body: NewVersion, p: Principal = who) -> dict[str, Any]:
        return await make_version(p, body.tenant_id, document_id, body.title, body.text, "paste", None)

    if parser is not None and blobs is not None:
        file_parser = parser

        async def read_file(file: UploadFile) -> tuple[bytes, str, str]:
            """Returns (original bytes, extracted text, kind). Everything that can go wrong with the
            file is a 4xx with a message the uploader can act on."""
            try:
                data = await file.read(max_file_bytes + 1)
            finally:
                await file.close()
            if len(data) > max_file_bytes:
                raise HTTPException(status_code=413, detail=f"the file is too large (limit {max_file_bytes // 1_000_000} MB)")
            if not data:
                raise HTTPException(status_code=422, detail="the file is empty")
            try:
                parsed = await asyncio.wait_for(asyncio.to_thread(file_parser.parse, data), PARSE_TIMEOUT)
            except FileRejected as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except TimeoutError:
                raise HTTPException(status_code=422, detail="reading the file took too long") from None
            except Exception as exc:  # noqa: BLE001
                log.warning("file parsing failed: %r", exc)
                raise HTTPException(status_code=422, detail="the file could not be read") from exc
            return data, parsed.text, f"file:{parsed.kind}"

        @router.post("/documents/upload", status_code=201)
        async def upload_document(
            tenant_id: Annotated[str, Form(max_length=64)],
            title: Annotated[str, Form(min_length=1, max_length=200)],
            groups: Annotated[str, Form()],
            file: UploadFile,
            p: Principal = who,
        ) -> dict[str, Any]:
            await authorize(p, tenant_id, "document.create")  # before spending effort on the file
            names = parse_groups(groups)
            if p.group_scoped and p.group not in names:
                await deny(p, tenant_id, "document.create", "", "a group administrator's documents must include their own group")
            data, text, source = await read_file(file)
            return await make_document(p, tenant_id, title, text, names, source, data)

        @router.post("/documents/{document_id}/versions/upload", status_code=202)
        async def upload_version(
            document_id: str,
            tenant_id: Annotated[str, Form(max_length=64)],
            title: Annotated[str, Form(min_length=1, max_length=200)],
            file: UploadFile,
            p: Principal = who,
        ) -> dict[str, Any]:
            await authorize_doc(p, tenant_id, "document.version", document_id)
            data, text, source = await read_file(file)
            return await make_version(p, tenant_id, document_id, title, text, source, data)

    @router.delete("/documents/{document_id}", status_code=202)
    async def delete_document(document_id: str, tenant: str, p: Principal = who) -> dict[str, Any]:
        await authorize_doc(p, tenant, "document.delete", document_id)
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
        if p.group_scoped:
            await deny(
                p, body.tenant_id, "simulate", body.document_id,
                "simulations need a tenant or platform administrator",
            )  # fmt: skip
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

