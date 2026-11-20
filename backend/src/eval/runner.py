from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from domain.models import DocumentId, GroupId, TenantId
from eval.metrics import dedupe, mean, ndcg_at_k, percentile, recall_at_k, reciprocal_rank
from eval.scoring import AskResult, score_answer
from ingestion.corpus import GROUPS, CorpusDoc, GoldenQuery

SetAcl = Callable[[TenantId, DocumentId, Collection[GroupId]], Awaitable[int]]


def request_headers(tenant: str, group: str, epoch: int = 0) -> dict[str, str]:
    return {
        "X-Tenant-Id": tenant,
        "X-User-Id": "eval",
        "X-Groups": group,
        "X-Policy-Epoch": str(epoch),
    }


async def _search(
    client: httpx.AsyncClient, tenant: str, group: str, query: str, k: int, epoch: int = 0
) -> tuple[list[dict[str, Any]], float]:
    t0 = time.perf_counter()
    r = await client.post(
        "/search", json={"query": query, "top_k": k}, headers=request_headers(tenant, group, epoch)
    )
    ms = (time.perf_counter() - t0) * 1000
    r.raise_for_status()
    hits: list[dict[str, Any]] = r.json()["hits"]
    return hits, ms


# ---------------------------------------------------------------- retrieval quality


@dataclass(frozen=True, slots=True)
class RetrievalReport:
    n: int
    recall_at_5: float
    recall_at_10: float
    mrr: float
    ndcg_at_10: float
    latency_p50_ms: float
    latency_p95_ms: float


async def run_retrieval(
    client: httpx.AsyncClient, golden: Sequence[GoldenQuery], *, concurrency: int = 4
) -> RetrievalReport:
    """Document-level metrics: chunk hits are collapsed to a ranked list of documents."""
    sem = asyncio.Semaphore(concurrency)

    async def one(g: GoldenQuery) -> tuple[float, float, float, float, float]:
        async with sem:
            hits, ms = await _search(client, g.tenant_id, g.group_id, g.question, 10)
        ranked = dedupe([str(h["document_id"]) for h in hits])
        relevant = {str(g.relevant_doc_id)}
        return (
            recall_at_k(ranked, relevant, 5),
            recall_at_k(ranked, relevant, 10),
            reciprocal_rank(ranked, relevant),
            ndcg_at_k(ranked, relevant, 10),
            ms,
        )

    rows = await asyncio.gather(*(one(g) for g in golden))
    latencies = [r[4] for r in rows]
    return RetrievalReport(
        n=len(rows),
        recall_at_5=mean([r[0] for r in rows]),
        recall_at_10=mean([r[1] for r in rows]),
        mrr=mean([r[2] for r in rows]),
        ndcg_at_10=mean([r[3] for r in rows]),
        latency_p50_ms=percentile(latencies, 50),
        latency_p95_ms=percentile(latencies, 95),
    )


# ---------------------------------------------------------------- answer quality


@dataclass(frozen=True, slots=True)
class AnswerReport:
    n: int
    answerable: int
    unanswerable: int
    correct_rate: float  # answerable questions answered correctly and grounded
    refusal_correct_rate: float  # unanswerable questions correctly refused
    cited_relevant_rate: float  # answerable questions that cite the right document
    hallucination_rate: float  # answers containing an unsupported number
    degraded_rate: float
    latency_p50_ms: float
    latency_p95_ms: float
    failures: tuple[str, ...]


async def run_answers(
    client: httpx.AsyncClient,
    golden: Sequence[GoldenQuery],
    texts: Mapping[str, str],
    *,
    concurrency: int = 2,
) -> AnswerReport:
    sem = asyncio.Semaphore(concurrency)

    async def one(g: GoldenQuery) -> tuple[GoldenQuery, AskResult, float]:
        async with sem:
            t0 = time.perf_counter()
            r = await client.post(
                "/ask",
                json={"question": g.question, "top_k": 5},
                headers=request_headers(g.tenant_id, g.group_id),
            )
            ms = (time.perf_counter() - t0) * 1000
        r.raise_for_status()
        body = r.json()
        result = AskResult(
            answer=body["answer"],
            grounded=body["grounded"],
            degraded=tuple(body["degraded"]),
            cited=tuple(
                (c["document_id"], c["start_offset"], c["end_offset"]) for c in body["citations"]
            ),
        )
        return g, result, ms

    rows = await asyncio.gather(*(one(g) for g in golden))
    scored = [(g, r, ms, score_answer(g, r, texts)) for g, r, ms in rows]
    yes = [s for s in scored if s[3].answerable]
    no = [s for s in scored if not s[3].answerable]
    failures = tuple(
        f"[{'should answer' if s[3].answerable else 'should refuse'}] "
        f"{s[0].tenant_id}/{s[0].group_id} {s[0].relevant_doc_id}: {s[0].question} "
        f"-> {s[1].answer[:90]}"
        for s in scored
        if not s[3].correct
    )[:5]
    latencies = [s[2] for s in scored]
    return AnswerReport(
        n=len(scored),
        answerable=len(yes),
        unanswerable=len(no),
        correct_rate=mean([float(s[3].correct) for s in yes]),
        refusal_correct_rate=mean([float(s[3].correct) for s in no]),
        cited_relevant_rate=mean([float(s[3].cited_relevant) for s in yes]),
        hallucination_rate=mean([float(s[3].hallucinated) for s in scored]),
        degraded_rate=mean([float(bool(s[1].degraded)) for s in scored]),
        latency_p50_ms=percentile(latencies, 50),
        latency_p95_ms=percentile(latencies, 95),
        failures=failures,
    )


# ---------------------------------------------------------------- permission audit


@dataclass(frozen=True, slots=True)
class AuditReport:
    requests: int
    violations: tuple[str, ...]


async def audit_permissions(
    client: httpx.AsyncClient,
    corpus: Sequence[CorpusDoc],
    golden: Sequence[GoldenQuery],
    *,
    per_tenant: int = 10,
    concurrency: int = 4,
) -> AuditReport:
    """Ask every sampled question as every group of every tenant, plus a group with no access
    and an unknown tenant. Any returned document that the caller may not read is a violation.
    The ground truth (owner tenant and allowed groups) comes from the corpus, not the system."""
    owner = {str(d.document_id): d for d in corpus}
    jobs: list[tuple[str, str, str]] = []
    for tenant in sorted({d.tenant_id for d in corpus}):
        for g in [x for x in golden if x.tenant_id == tenant][:per_tenant]:
            for group in (*GROUPS, GroupId("nobody")):
                jobs.append((tenant, group, g.question))
    jobs.append(("tenant-unknown", "eng", golden[0].question))

    sem = asyncio.Semaphore(concurrency)

    async def one(job: tuple[str, str, str]) -> list[str]:
        tenant, group, query = job
        async with sem:
            hits, _ = await _search(client, tenant, group, query, 10)
        bad: list[str] = []
        for h in hits:
            doc = owner.get(str(h["document_id"]))
            if doc is None and str(h["document_id"]).startswith("u-"):
                continue  # uploaded through the UI: no ground truth in the corpus
            if doc is None or doc.tenant_id != tenant or group not in doc.groups:
                bad.append(f"{tenant}/{group} saw {h['document_id']}")
        return bad

    results = await asyncio.gather(*(one(j) for j in jobs))
    return AuditReport(len(jobs), tuple(v for r in results for v in r))


# ---------------------------------------------------------------- revocation


@dataclass(frozen=True, slots=True)
class RevocationReport:
    runs: int
    blocked_on_first_request: int
    max_ms: float
    skipped: str = ""


async def probe_revocation(
    client: httpx.AsyncClient, set_acl: SetAcl, corpus: Sequence[CorpusDoc], *, runs: int = 3
) -> RevocationReport:
    """Revoke a group's access, then measure how soon a request pinned at the returned epoch
    stops seeing the document. The ACL is always restored afterwards."""
    doc = next((d for d in corpus if len(d.groups) == 1), None)
    if doc is None:
        return RevocationReport(0, 0, 0.0, "no single-group document in the corpus")
    group = doc.groups[0]

    before, _ = await _search(client, doc.tenant_id, group, doc.title, 10)
    if str(doc.document_id) not in {str(h["document_id"]) for h in before}:
        return RevocationReport(0, 0, 0.0, "document not retrievable before revocation")

    blocked = 0
    worst = 0.0
    for _ in range(runs):
        epoch = await set_acl(doc.tenant_id, doc.document_id, [GroupId("revoked-probe")])
        try:
            hits, ms = await _search(client, doc.tenant_id, group, doc.title, 10, epoch)
            worst = max(worst, ms)
            if str(doc.document_id) not in {str(h["document_id"]) for h in hits}:
                blocked += 1
        finally:
            await set_acl(doc.tenant_id, doc.document_id, doc.groups)
    return RevocationReport(runs, blocked, worst)


