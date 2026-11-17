"""
Admin is off unless RAG_ADMIN=1. If it’s on without a strong key, the server refuses to start. Every route needs the X-Admin-Key header.
"""

import hmac
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from domain.models import DocumentId, GroupId, TenantId
from domain.ops_ports import AclAdmin, DeadLetterInspector, StateScanner
from domain.ports import DocStateStore
from eval.gate import check_gate

MIN_KEY_CHARS = 16


class AclUpdate(BaseModel):
    tenant_id: str = Field(min_length=1)
    groups: list[str] = Field(max_length=50)  # an empty list means "nobody", a full revocation


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


def create_admin_router(
    states: DocStateStore,
    scanner: StateScanner,
    acls: AclAdmin,
    dlq: DeadLetterInspector,
    *,
    admin_key: str,
    data_dir: Path,
) -> APIRouter:
    router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin(admin_key))])

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

    return router



