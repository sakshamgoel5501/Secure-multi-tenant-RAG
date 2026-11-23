import asyncio

import pytest

from adapters.llm_decomposer import parse_parts
from domain.errors import AuthzUnavailable, RetrievalUnavailable
from domain.fusion import interleave
from domain.models import (
    ChunkId, DocumentId, GroupId, RetrievalSource, SearchHit, SecurityContext, TenantId, UserId,
)  # fmt: skip
from serving.planner import PlannedRetriever
from serving.query_service import RetrievalResult

T = TenantId("t1")
CTX = SecurityContext(T, UserId("u"), frozenset({GroupId("g")}), 0)
MULTI = "Compare the leave policy and the travel policy"


def hit(doc: str) -> SearchHit:
    return SearchHit(
        ChunkId(f"{doc}:1:0"), T, DocumentId(doc), 1, doc, None, 0, 1, doc, 1.0, RetrievalSource.HYBRID
    )


class Inner:
    def __init__(self, by_query: dict[str, list[str]], fail: dict[str, Exception] | None = None) -> None:
        self.by_query = by_query
        self.fail = fail or {}
        self.calls: list[str] = []

    async def retrieve_ex(self, ctx: SecurityContext, query: str, top_k: int) -> RetrievalResult:
        self.calls.append(query)
        if query in self.fail:
            raise self.fail[query]
        return RetrievalResult([hit(d) for d in self.by_query.get(query, [])][:top_k], ())


class Splitter:
    def __init__(self, parts: list[str] | Exception, delay: float = 0.0) -> None:
        self.parts = parts
        self.delay = delay
        self.calls = 0

    async def decompose(self, query: str) -> list[str]:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.parts, Exception):
            raise self.parts
        return self.parts


BY_QUERY = {"leave policy": ["a1", "a2", "a3"], "travel policy": ["b1", "b2"], MULTI: ["z1"]}


async def test_simple_questions_never_call_the_decomposer() -> None:
    inner, splitter = Inner(BY_QUERY), Splitter(["x", "y"])
    result = await PlannedRetriever(inner, splitter).retrieve_ex(CTX, "leave policy", 4)
    assert inner.calls == ["leave policy"] and splitter.calls == 0
    assert result.queries == ()


async def test_a_multi_part_question_is_split_and_interleaved() -> None:
    inner = Inner(BY_QUERY)
    planner = PlannedRetriever(inner, Splitter(["leave policy", "travel policy"]))
    result = await planner.retrieve_ex(CTX, MULTI, 4)
    assert [h.document_id for h in result.hits] == ["a1", "b1", "a2", "b2"]
    assert result.queries == ("leave policy", "travel policy")
    assert sorted(inner.calls) == ["leave policy", "travel policy"]


async def test_one_part_or_none_uses_the_original_question() -> None:
    for parts in (["only one"], []):
        inner = Inner(BY_QUERY)
        result = await PlannedRetriever(inner, Splitter(parts)).retrieve_ex(CTX, MULTI, 4)
        assert inner.calls == [MULTI] and result.queries == ()


async def test_decomposer_failure_and_timeout_degrade_to_the_original_question() -> None:
    for splitter in (Splitter(RuntimeError("down")), Splitter(["a", "b"], delay=1.0)):
        inner = Inner(BY_QUERY)
        result = await PlannedRetriever(inner, splitter, timeout=0.05).retrieve_ex(CTX, MULTI, 4)
        assert inner.calls == [MULTI]
        assert [h.document_id for h in result.hits] == ["z1"]
        assert "decompose" in result.degraded


async def test_parts_are_capped() -> None:
    inner = Inner({})
    await PlannedRetriever(inner, Splitter(["a", "b", "c", "d", "e"]), max_parts=3).retrieve_ex(CTX, MULTI, 4)
    assert sorted(inner.calls) == ["a", "b", "c"]


async def test_a_permission_failure_in_any_part_fails_the_whole_request() -> None:
    inner = Inner(BY_QUERY, {"travel policy": AuthzUnavailable("replica behind")})
    planner = PlannedRetriever(inner, Splitter(["leave policy", "travel policy"]))
    with pytest.raises(AuthzUnavailable):
        await planner.retrieve_ex(CTX, MULTI, 4)


async def test_one_failed_part_degrades_but_the_others_still_answer() -> None:
    inner = Inner(BY_QUERY, {"travel policy": RetrievalUnavailable("down")})
    planner = PlannedRetriever(inner, Splitter(["leave policy", "travel policy"]))
    result = await planner.retrieve_ex(CTX, MULTI, 4)
    assert [h.document_id for h in result.hits] == ["a1", "a2", "a3"]
    assert "subquery" in result.degraded


async def test_every_part_failing_raises() -> None:
    err = RetrievalUnavailable("down")
    inner = Inner({}, {"a": err, "b": err})
    with pytest.raises(RetrievalUnavailable):
        await PlannedRetriever(inner, Splitter(["a", "b"])).retrieve_ex(CTX, MULTI, 4)


def test_interleave_drops_duplicates_and_respects_the_limit() -> None:
    merged = interleave([[hit("a"), hit("b")], [hit("a"), hit("c")]], limit=3)
    assert [h.document_id for h in merged] == ["a", "b", "c"]
    assert len(interleave([[hit("a"), hit("b")], [hit("c")]], limit=2)) == 2
    assert interleave([], 5) == []


def test_parse_parts_is_forgiving_and_bounded() -> None:
    assert parse_parts('```json\n["a", "b"]\n```', 3) == ["a", "b"]
    assert parse_parts('["a", "a", " ", 3, "b", "c", "d"]', 3) == ["a", "b", "c"]
    assert parse_parts("I don't have enough information.", 3) == []
    assert parse_parts('{"not": "a list"}', 3) == []
    assert parse_parts('["' + "x" * 400 + '"]', 3) == []

    