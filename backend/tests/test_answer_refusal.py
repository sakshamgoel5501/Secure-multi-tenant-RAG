from typing import cast

from domain.models import (
    ChunkId,
    DocumentId,
    GroupId,
    RetrievalSource,
    SearchHit,
    SecurityContext,
    TenantId,
    UserId,
)
from serving.answer_service import NO_INFO, AnswerService
from serving.query_service import QueryService, RetrievalResult

HIT = SearchHit(
    ChunkId("d1:1:0"), TenantId("t1"), DocumentId("d1"), 1, "Doc", None, 0, 5, "hello",
    1.0, RetrievalSource.HYBRID,
)


class StubRetrieval:
    async def retrieve_ex(self, ctx: SecurityContext, query: str, top_k: int) -> RetrievalResult:
        return RetrievalResult([HIT], ())


class RefusingLLM:
    async def generate(self, system: str, user: str) -> str:
        return f"{NO_INFO} [S1]"  # even a refusal that tacks on a citation


async def test_refusal_is_never_grounded_and_carries_no_citations() -> None:
    service = AnswerService(cast(QueryService, StubRetrieval()), RefusingLLM())
    ctx = SecurityContext(TenantId("t1"), UserId("u"), frozenset({GroupId("g")}), 0)
    result = await service.ask(ctx, "q")
    assert not result.grounded
    assert result.citations == ()
    assert result.text == NO_INFO



    