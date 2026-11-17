from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from eval.runner import request_headers
from ingestion.corpus import GoldenQuery, generate_corpus


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    fail: tuple[str, ...] = ()
    delay: tuple[tuple[str, float], ...] = ()
    status: int = 200  # expected HTTP status
    degraded: tuple[str, ...] = ()  # stages that must be reported as degraded
    grounded: bool | None = None
    bounded: bool = False  # latency must stay well under the injected delay (timeout worked)


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    name: str
    ok: bool
    detail: str
    worst_ms: float


def default_scenarios(delay: float = 6.0) -> list[Scenario]:
    return [
        Scenario("baseline", grounded=True),
        Scenario("reranker_down", fail=("reranker",), degraded=("reranker",), grounded=True),
        Scenario(
            "reranker_slow",
            delay=(("reranker", delay),),
            degraded=("reranker",),
            grounded=True,
            bounded=True,
        ),
        Scenario("dense_down", fail=("dense",), degraded=("dense",)),
        Scenario("lexical_down", fail=("lexical",), degraded=("lexical",)),
        Scenario("retrieval_down", fail=("dense", "lexical"), status=503),
        Scenario("state_down", fail=("state",), status=503),
        Scenario("acl_down", fail=("acl",), status=503),
        Scenario("llm_down", fail=("llm",), degraded=("generation",), grounded=False),
        Scenario(
            "llm_slow",
            delay=(("llm", delay),),
            degraded=("generation",),
            grounded=False,
            bounded=True,
        ),
    ]


def _check(sc: Scenario, status: int, body: dict[str, object], ms: float) -> list[str]:
    if status != sc.status:
        return [f"status {status}, expected {sc.status}"]
    if status == 503:
        return ["503 body carries an answer"] if "answer" in body else []
    problems: list[str] = []
    degraded = body["degraded"]
    assert isinstance(degraded, list)
    missing = set(sc.degraded) - set(degraded)
    if missing:
        problems.append(f"not reported as degraded: {sorted(missing)}")
    if not sc.degraded and degraded:
        problems.append(f"unexpected degradation: {degraded}")
    if sc.grounded is not None and body["grounded"] is not sc.grounded:
        problems.append(f"grounded={body['grounded']}, expected {sc.grounded}")
    if sc.bounded:
        limit = 0.8 * max(d for _, d in sc.delay) * 1000
        if ms > limit:
            problems.append(f"{ms:.0f} ms: timeout did not cut the {limit / 0.8:.0f} ms stall")
    return problems


async def run_scenarios(
    client: httpx.AsyncClient,
    scenarios: Sequence[Scenario],
    golden: GoldenQuery,
    *,
    repeats: int = 3,
) -> list[ScenarioResult]:
    headers = request_headers(golden.tenant_id, golden.group_id)
    results: list[ScenarioResult] = []
    for sc in scenarios:
        (await client.post("/chaos", json={"fail": list(sc.fail), "delay": dict(sc.delay)})).raise_for_status()
        problems: list[str] = []
        worst = 0.0
        try:
            for _ in range(repeats):
                started = time.perf_counter()
                r = await client.post(
                    "/ask", json={"question": golden.question, "top_k": 5}, headers=headers
                )
                ms = (time.perf_counter() - started) * 1000
                worst = max(worst, ms)
                problems += _check(sc, r.status_code, r.json(), ms)
        finally:
            await client.delete("/chaos")
        detail = "; ".join(dict.fromkeys(problems)) or "ok"
        results.append(ScenarioResult(sc.name, not problems, detail, worst))
    return results


async def amain(args: argparse.Namespace) -> int:
    _, golden = generate_corpus(args.tenants, args.docs, args.seed)
    question = next(g for g in golden if g.answerable and g.tenant_id == "tenant-1")
    async with httpx.AsyncClient(base_url=args.base_url, timeout=60.0) as client:
        results = await run_scenarios(
            client, default_scenarios(args.delay), question, repeats=args.repeats
        )
    print(f"\n{'scenario':<16} {'result':<6} {'worst ms':>9}  detail")
    for r in results:
        print(f"{r.name:<16} {'PASS' if r.ok else 'FAIL':<6} {r.worst_ms:>9.0f}  {r.detail}")
    failed = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} scenarios passed")
    return 1 if failed else 0


def main() -> None:
    p = argparse.ArgumentParser(description="Fault-injection run against a server with RAG_CHAOS=1")
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--tenants", type=int, default=3)
    p.add_argument("--docs", type=int, default=40)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--delay", type=float, default=6.0, help="seconds of injected stall")
    p.add_argument("--repeats", type=int, default=3)
    sys.exit(asyncio.run(amain(p.parse_args())))


if __name__ == "__main__":
    main()


    