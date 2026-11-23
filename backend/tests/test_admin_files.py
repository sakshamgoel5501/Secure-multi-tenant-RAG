from dataclasses import dataclass
from pathlib import Path

import httpx
from admin_tokens import admin_headers
from fastapi import FastAPI
from file_samples import make_docx, make_pdf
from test_admin_lifecycle import Acls, Dlq, InlineBus, Scanner

from adapters.fake_embedder import HashEmbedder
from adapters.file_parsers import DefaultFileParser
from adapters.memory_audit import InMemoryAuditLog
from adapters.memory_blobs import InMemoryBlobStore
from adapters.memory_doc_state import InMemoryDocStateStore
from adapters.memory_vector_store import InMemoryVectorStore
from adapters.simple_chunker import ParagraphChunker
from domain.models import DocumentId, GroupId, SecurityContext, TenantId, UserId
from ingestion.worker import IngestionWorker
from serving.admin import create_admin_router

KEY = "k" * 32
T = TenantId("t1")
BOSS = admin_headers(KEY, "tenant_admin", "t1")
ENG = admin_headers(KEY, "group_admin", "t1", "eng")
CTX = SecurityContext(T, UserId("u"), frozenset({GroupId("eng")}), 1)


@dataclass
class Env:
    client: httpx.AsyncClient
    state: InMemoryDocStateStore
    vectors: InMemoryVectorStore
    acls: Acls
    bus: InlineBus
    blobs: InMemoryBlobStore
    audit: InMemoryAuditLog


def build(tmp_path: Path, *, max_file_bytes: int = 1_000_000) -> Env:
    state, vectors = InMemoryDocStateStore(), InMemoryVectorStore()
    worker = IngestionWorker(state, vectors, ParagraphChunker(max_chars=400), HashEmbedder())
    bus, acls, blobs, audit = InlineBus(worker), Acls(), InMemoryBlobStore(), InMemoryAuditLog()
    app = FastAPI()
    app.include_router(
        create_admin_router(
            state, Scanner(), acls, Dlq(), admin_key=KEY, data_dir=tmp_path, audit=audit,
            publisher=bus, blobs=blobs, parser=DefaultFileParser(), max_file_bytes=max_file_bytes,
        )
    )  # fmt: skip
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return Env(client, state, vectors, acls, bus, blobs, audit)


async def upload(
    env: Env, content: bytes, *, name: str = "plan.txt", groups: str = "eng",
    headers: dict[str, str] = BOSS, tenant: str = "t1",
) -> httpx.Response:  # fmt: skip
    return await env.client.post(
        "/admin/documents/upload",
        data={"tenant_id": tenant, "title": "Plan", "groups": groups},
        files={"file": (name, content, "application/octet-stream")},
        headers=headers,
    )


def nothing_changed(env: Env) -> bool:
    return env.bus.events == [] and env.acls.data == {} and env.blobs.data == {}


async def test_a_text_file_is_indexed_and_its_original_and_text_are_kept(tmp_path: Path) -> None:
    env = build(tmp_path)
    r = await upload(env, b"Launch code is ALPHA.\n\nSecond paragraph.", name="secret-plan.txt")
    assert r.status_code == 201
    doc = DocumentId(r.json()["document_id"])
    assert await env.blobs.get(T, doc, 1, "original") == b"Launch code is ALPHA.\n\nSecond paragraph."
    assert (await env.blobs.get(T, doc, 1, "text") or b"").decode().startswith("Launch code")
    assert b'"Plan"' in (await env.blobs.get(T, doc, 1, "meta") or b"")
    state = await env.state.get(T, doc)
    assert state is not None and state.active_version == 1
    assert any("ALPHA" in h.text for h in await env.vectors.search(CTX, (0.5,) * 8, 10))
    assert "secret-plan" not in str([(e.action, e.target, e.detail) for e in env.audit.entries])
    assert env.audit.entries[-1].detail["source"] == "file:text"


async def test_pdf_and_docx_uploads_are_extracted_and_indexed(tmp_path: Path) -> None:
    env = build(tmp_path)
    assert (await upload(env, make_pdf("Quarterly budget is large"), name="q.pdf")).status_code == 201
    assert (await upload(env, make_docx(["Policy on leave"]), name="p.docx")).status_code == 201
    texts = " ".join(h.text for h in await env.vectors.search(CTX, (0.5,) * 8, 10))
    assert "Quarterly budget" in texts and "Policy on leave" in texts


async def test_bad_files_are_refused_before_anything_changes(tmp_path: Path) -> None:
    env = build(tmp_path)
    for content in (b"\x00\x01binary", make_pdf(""), b""):
        assert (await upload(env, content)).status_code == 422
    assert nothing_changed(env)


async def test_an_oversized_file_is_refused_with_413(tmp_path: Path) -> None:
    env = build(tmp_path, max_file_bytes=100)
    assert (await upload(env, b"x" * 101)).status_code == 413
    assert nothing_changed(env)


async def test_another_tenants_admin_is_denied_before_the_file_is_read(tmp_path: Path) -> None:
    env = build(tmp_path)
    assert (await upload(env, b"hello", tenant="t2")).status_code == 403
    assert nothing_changed(env)


async def test_a_group_admin_must_include_their_own_group(tmp_path: Path) -> None:
    env = build(tmp_path)
    assert (await upload(env, b"hello", groups="hr", headers=ENG)).status_code == 403
    assert nothing_changed(env)
    assert (await upload(env, b"hello", groups="eng,hr", headers=ENG)).status_code == 201


async def test_a_new_version_can_come_from_a_file(tmp_path: Path) -> None:
    env = build(tmp_path)
    doc = (await upload(env, b"version one")).json()["document_id"]
    r = await env.client.post(
        f"/admin/documents/{doc}/versions/upload",
        data={"tenant_id": "t1", "title": "Plan"},
        files={"file": ("v2.txt", b"version two", "text/plain")},
        headers=BOSS,
    )
    assert r.status_code == 202 and r.json()["version"] == 2
    assert await env.blobs.get(T, DocumentId(doc), 2, "original") == b"version two"
    state = await env.state.get(T, DocumentId(doc))
    assert state is not None and state.active_version == 2


async def test_a_file_store_outage_changes_nothing(tmp_path: Path) -> None:
    env = build(tmp_path)
    env.blobs.fail = True
    assert (await upload(env, b"hello")).status_code == 503
    assert env.bus.events == [] and env.acls.data == {}


async def test_pasted_text_is_kept_too_so_the_index_can_be_rebuilt(tmp_path: Path) -> None:
    env = build(tmp_path)
    r = await env.client.post(
        "/admin/documents",
        json={"tenant_id": "t1", "title": "Note", "text": "pasted words", "groups": ["eng"]},
        headers=BOSS,
    )
    doc = DocumentId(r.json()["document_id"])
    assert await env.blobs.get(T, doc, 1, "text") == b"pasted words"
    assert await env.blobs.get(T, doc, 1, "original") is None


async def test_capabilities_report_file_support(tmp_path: Path) -> None:
    env = build(tmp_path)
    caps = (await env.client.get("/admin/capabilities", headers=BOSS)).json()
    assert caps["files"] is True


    