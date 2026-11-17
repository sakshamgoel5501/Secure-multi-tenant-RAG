"""
Runs the real harness against an in-memory app. The leaky-ACL test checks the auditor itself, since an 
auditor that can’t fail is worthless.
"""

from collections.abc import Collection
from dataclasses import dataclass

import httpx

from adapters.fake_embedder import HashEmbedder
from adapters.fake_llm import ExtractiveLLM
from adapters.memory_acl import InMemoryAclPrimary, InMemoryAclReplica
from adapters.memory_doc_state import InMemoryDocStateStore
from adapters.memory_lexical import InMemoryLexicalStore
from adapters.memory_vector_store import InMemoryVectorStore
from adapters.simple_chunker import ParagraphChunker
from domain.models import AclSnapshot, DocumentEvent, DocumentId, GroupId, Operation, TenantId
from domain.ports import AclReader
from eval.runner import (
    SetAcl,
    audit_permissions,
    probe_revocation,
    request_headers,
    run_answers,
    run_retrieval,
)
from ingestion.corpus import CorpusDoc, GoldenQuery, generate_corpus
from ingestion.worker import IngestionWorker
from serving.answer_service import AnswerService
from serving.api import create_app
from serving.query_service import QueryService


class LeakyAcl:
    """A broken ACL layer that grants every group (including 'nobody') on every document."""

    async def acls_for(
        self, tenant_id: TenantId, document_ids: Collection[DocumentId], *, min_epoch: int
    ) -> AclSnapshot:
        everyone = frozenset(map(GroupId, ("eng", "hr", "fin", "nobody")))
        return AclSnapshot(min_epoch, {d: everyone for d in document_ids})


@dataclass
class Stack:
    client: httpx.AsyncClient
    corpus: list[CorpusDoc]
    golden: list[GoldenQuery]
    set_acl: SetAcl


async def build(leaky: bool = False) -> Stack:
    corpus, golden = generate_corpus(2, 10, seed=1)
    state = InMemoryDocStateStore()
    vectors = InMemoryVectorStore()
    lexical = InMemoryLexicalStore()
    embedder = HashEmbedder()
    worker = IngestionWorker(state, vectors, ParagraphChunker(max_chars=400), embedder, lexical)
    primary = InMemoryAclPrimary()
    replica = InMemoryAclReplica(primary)
    for d in corpus:
        await worker.handle(
            DocumentEvent(Operation.UPSERT, d.tenant_id, d.document_id, 1, d.title, d.text)
        )
        primary.set_acl(d.tenant_id, d.document_id, d.groups)
    replica.sync()

    async def set_acl(t: TenantId, d: DocumentId, groups: Collection[GroupId]) -> int:
        epoch = primary.set_acl(t, d, groups)
        replica.sync()
        return epoch

    acl: AclReader = LeakyAcl() if leaky else replica
    service = QueryService(state, vectors, embedder, acl, lexical=lexical)
    app = create_app(service, answers=AnswerService(service, ExtractiveLLM()))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return Stack(client, corpus, golden, set_acl)


async def test_audit_finds_no_violations_in_a_correct_system() -> None:
    s = await build()
    report = await audit_permissions(s.client, s.corpus, s.golden, per_tenant=3)
    assert report.requests > 0
    assert report.violations == ()


async def test_audit_detects_a_leaky_system() -> None:
    s = await build(leaky=True)
    report = await audit_permissions(s.client, s.corpus, s.golden, per_tenant=3)
    assert report.violations != ()


async def test_revocation_is_enforced_on_the_first_request_and_acl_is_restored() -> None:
    s = await build()
    report = await probe_revocation(s.client, s.set_acl, s.corpus, runs=2)
    assert report.skipped == ""
    assert report.blocked_on_first_request == report.runs == 2

    doc = next(d for d in s.corpus if len(d.groups) == 1)
    r = await s.client.post(
        "/search",
        json={"query": doc.title, "top_k": 10},
        headers=request_headers(doc.tenant_id, doc.groups[0]),
    )
    assert str(doc.document_id) in {h["document_id"] for h in r.json()["hits"]}


async def test_retrieval_report_values_are_sane() -> None:
    s = await build()
    rep = await run_retrieval(s.client, s.golden)
    assert rep.n == len(s.golden)
    assert 0.0 <= rep.mrr <= 1.0
    assert rep.recall_at_10 >= rep.recall_at_5


async def test_answer_report_runs_end_to_end() -> None:
    s = await build()
    texts = {str(d.document_id): d.text for d in s.corpus}
    rep = await run_answers(s.client, s.golden[:6], texts)
    assert rep.n == 6
    assert rep.answerable + rep.unanswerable == 6
    assert 0.0 <= rep.correct_rate <= 1.0




    
