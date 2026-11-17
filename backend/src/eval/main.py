from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

from adapters.postgres_acl import PostgresAclStore
from eval.gate import check_gate
from eval.runner import (
    audit_permissions,
    probe_revocation,
    request_headers,
    run_answers,
    run_retrieval,
)
from ingestion.corpus import generate_corpus


async def amain(args: argparse.Namespace) -> int:
    corpus, golden = generate_corpus(args.tenants, args.docs, args.seed)
    texts = {str(d.document_id): d.text for d in corpus}
    summary: dict[str, float] = {}

    async with httpx.AsyncClient(base_url=args.base_url, timeout=60.0) as client:
        await client.post(  # warm-up so the first measured request isn't a cold start
            "/search", json={"query": "warm up"}, headers=request_headers("tenant-1", "eng")
        )

        ret = await run_retrieval(client, golden)
        print(f"\nRETRIEVAL ({ret.n} queries)")
        print(f"  recall@5 {ret.recall_at_5:.3f}   recall@10 {ret.recall_at_10:.3f}")
        print(f"  MRR {ret.mrr:.3f}   nDCG@10 {ret.ndcg_at_10:.3f}")
        print(f"  latency p50 {ret.latency_p50_ms:.0f} ms   p95 {ret.latency_p95_ms:.0f} ms")
        summary.update(
            recall_at_5=ret.recall_at_5,
            recall_at_10=ret.recall_at_10,
            mrr=ret.mrr,
            ndcg_at_10=ret.ndcg_at_10,
            retrieval_latency_p95_ms=ret.latency_p95_ms,
        )

        if args.answer_sample > 0:
            step = max(1, len(golden) // args.answer_sample)
            ans = await run_answers(client, golden[::step][: args.answer_sample], texts)
            print(f"\nANSWERS ({ans.n}: {ans.answerable} answerable, {ans.unanswerable} unanswerable)")
            print(f"  correct {ans.correct_rate:.3f}   cites right doc {ans.cited_relevant_rate:.3f}")
            print(f"  correctly refused {ans.refusal_correct_rate:.3f}")
            print(f"  hallucination {ans.hallucination_rate:.3f}   degraded {ans.degraded_rate:.3f}")
            print(f"  latency p50 {ans.latency_p50_ms:.0f} ms   p95 {ans.latency_p95_ms:.0f} ms")
            for line in ans.failures:
                print(f"    fail: {line}")
            summary.update(
                answer_correct_rate=ans.correct_rate,
                refusal_correct_rate=ans.refusal_correct_rate,
                cited_relevant_rate=ans.cited_relevant_rate,
                hallucination_rate=ans.hallucination_rate,
                answer_latency_p95_ms=ans.latency_p95_ms,
            )

        audit = await audit_permissions(client, corpus, golden)
        print(f"\nPERMISSION AUDIT: {audit.requests} requests, {len(audit.violations)} violations")
        for v in audit.violations[:5]:
            print(f"    VIOLATION: {v}")
        summary["permission_violations"] = float(len(audit.violations))

        if args.revocation:
            acl = PostgresAclStore(os.environ.get("RAG_PG_DSN", "postgresql://localhost/rag"))
            await acl.start()
            try:
                rev = await probe_revocation(client, acl.set_acl, corpus)
            finally:
                await acl.close()
            if rev.skipped:
                print(f"\nREVOCATION: skipped ({rev.skipped})")
            else:
                print(
                    f"\nREVOCATION: {rev.blocked_on_first_request}/{rev.runs} blocked on the first "
                    f"request, worst {rev.max_ms:.0f} ms from set_acl return to a response without the doc"
                )
                summary["revocation_leaks"] = float(rev.runs - rev.blocked_on_first_request)
                summary["revocation_max_ms"] = rev.max_ms

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2))
    print(f"\nreport written to {out}")

    baseline = Path(args.baseline)
    if args.write_baseline:
        baseline.write_text(json.dumps(summary, indent=2))
        print(f"baseline saved to {baseline}")
        return 0
    if baseline.exists():
        failures = check_gate(summary, json.loads(baseline.read_text()), args.tolerance)
        if failures:
            print("\nGATE FAILED:")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("\nGATE PASSED")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Evaluate a running RAG server over HTTP")
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--tenants", type=int, default=3)
    p.add_argument("--docs", type=int, default=40)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--answer-sample", type=int, default=40, help="0 skips answer evaluation")
    p.add_argument("--revocation", action="store_true", help="needs RAG_PG_DSN")
    p.add_argument("--out", default="data/eval_report.json")
    p.add_argument("--baseline", default="data/baseline.json")
    p.add_argument("--write-baseline", action="store_true")
    p.add_argument("--tolerance", type=float, default=0.02)
    sys.exit(asyncio.run(amain(p.parse_args())))


if __name__ == "__main__":
    main()



    