import asyncio
from collections.abc import AsyncIterator
from typing import Any

from adapters.fake_llm import ExtractiveLLM
from domain.models import (
    ChunkId, DocumentId, GroupId, RetrievalSource, SearchHit, SecurityContext, TenantId, UserId,
)  # fmt: skip
from serving.answer_service import GENERATION_DOWN, NO_INFO, AnswerService
from serving.query_service import RetrievalResult

T = TenantId("t1")
CTX = SecurityContext(T, UserId("u"), frozenset({GroupId("g")}), 0)
HIT = SearchHit(
    ChunkId("d1:1:0"), T, DocumentId("d1"), 1, "Leave", None, 0, 20, "Twenty days of leave.",
    1.0, RetrievalSource.HYBRID,
)  # fmt: skip


class Retrieval:
    def __init__(self, hits: list[SearchHit], queries: tuple[str, ...] = ()) -> None:
        self.hits, self.queries = hits, queries

    async def retrieve_ex(self, ctx: SecurityContext, query: str, top_k: int) -> RetrievalResult:
        return RetrievalResult(self.hits, (), self.queries)


class StreamLLM:
    def __init__(self, chunks: list[str], fail_after: int | None = None, delay: float = 0.0) -> None:
        self.chunks, self.fail_after, self.delay, self.calls = chunks, fail_after, delay, 0

    async def generate(self, system: str, user: str) -> str:
        self.calls += 1
        return "".join(self.chunks)

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        self.calls += 1
        for i, chunk in enumerate(self.chunks):
            if self.fail_after is not None and i == self.fail_after:
                raise RuntimeError("boom")
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk


class PlainLLM:
    async def generate(self, system: str, user: str) -> str:
        return "Twenty days [S1]"


async def events(svc: AnswerService) -> list[tuple[str, dict[str, Any]]]:
    prepared = await svc.prepare(CTX, "how many days?")
    return [e async for e in svc.stream(prepared)]


def names(evs: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [n for n, _ in evs]


async def test_streams_sources_then_deltas_then_a_validated_final() -> None:
    svc = AnswerService(Retrieval([HIT]), StreamLLM(["Twenty days ", "of leave ", "[S1]."]))
    evs = await events(svc)
    assert names(evs) == ["sources", "delta", "delta", "delta", "final"]
    assert evs[0][1]["sources"][0]["text"] == "Twenty days of leave."
    final = evs[-1][1]
    assert final["grounded"] and final["answer"] == "Twenty days of leave [S1]."
    assert [c["document_id"] for c in final["citations"]] == ["d1"]
    assert final["timing"]["first_token_ms"] is not None


async def test_the_final_event_corrects_invented_citations_and_refusals() -> None:
    invented = await events(AnswerService(Retrieval([HIT]), StreamLLM(["Yes [S1] and ", "[S9]."])))
    assert "[S9]" in "".join(p["text"] for n, p in invented if n == "delta")  # provisional
    final = invented[-1][1]
    assert "[S9]" not in final["answer"] and final["grounded"]

    refusal = await events(AnswerService(Retrieval([HIT]), StreamLLM([NO_INFO, " [S1]"])))
    assert not refusal[-1][1]["grounded"] and refusal[-1][1]["citations"] == []
    assert refusal[-1][1]["answer"] == NO_INFO


async def test_no_evidence_means_no_model_call() -> None:
    llm = StreamLLM(["should not be used"])
    evs = await events(AnswerService(Retrieval([]), llm))
    assert names(evs) == ["sources", "final"] and llm.calls == 0
    assert evs[-1][1]["answer"] == NO_INFO and evs[-1][1]["timing"]["first_token_ms"] is None


async def test_a_failure_midway_falls_back_to_the_sources() -> None:
    evs = await events(AnswerService(Retrieval([HIT]), StreamLLM(["a ", "b ", "c"], fail_after=1)))
    final = evs[-1][1]
    assert final["answer"] == GENERATION_DOWN and not final["grounded"]
    assert "generation" in final["degraded"] and len(final["citations"]) == 1


async def test_a_slow_model_hits_the_timeout() -> None:
    svc = AnswerService(Retrieval([HIT]), StreamLLM(["a"], delay=1.0), generation_timeout=0.05)
    final = (await events(svc))[-1][1]
    assert "generation" in final["degraded"] and not final["grounded"]


async def test_a_model_that_cannot_stream_still_works() -> None:
    evs = await events(AnswerService(Retrieval([HIT]), PlainLLM()))
    assert names(evs) == ["sources", "delta", "final"] and evs[-1][1]["grounded"]


async def test_the_plan_is_reported() -> None:
    evs = await events(AnswerService(Retrieval([HIT], ("part one", "part two")), PlainLLM()))
    assert evs[0][1]["plan"] == ["part one", "part two"] == evs[-1][1]["plan"]


async def test_the_fake_llm_streams_word_by_word() -> None:
    svc = AnswerService(Retrieval([HIT]), ExtractiveLLM(delay=0))
    evs = await events(svc)
    deltas = [p["text"] for n, p in evs if n == "delta"]
    assert len(deltas) > 2 and "".join(deltas) == "Twenty days of leave. [S1]"

    