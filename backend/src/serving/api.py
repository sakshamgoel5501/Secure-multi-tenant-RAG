import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from domain.errors import AuthzUnavailable, RetrievalUnavailable, StateUnavailable
from domain.models import GroupId, SecurityContext, TenantId, UserId
from domain.tracing import finish_trace, start_trace
from serving.answer_service import AnswerService
from serving.query_service import QueryService
from serving.stats import StageStats


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=50)


class HitOut(BaseModel):
    chunk_id: str
    document_id: str
    version: int
    title: str
    section: str | None
    start_offset: int
    end_offset: int
    text: str
    score: float


class SearchResponse(BaseModel):
    hits: list[HitOut]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class CitationOut(BaseModel):
    marker: str
    chunk_id: str
    document_id: str
    version: int
    title: str
    section: str | None
    start_offset: int
    end_offset: int


class AskResponse(BaseModel):
    answer: str
    grounded: bool
    degraded: list[str]
    citations: list[CitationOut]


def get_security_context(
    x_tenant_id: Annotated[str, Header()],
    x_user_id: Annotated[str, Header()],
    x_groups: Annotated[str, Header()],
    x_policy_epoch: Annotated[int, Header()],
) -> SecurityContext:
    """DEV ONLY: trusts client headers. Production passes identity=jwt_identity(...)."""
    return SecurityContext(
        tenant_id=TenantId(x_tenant_id),
        user_id=UserId(x_user_id),
        group_ids=frozenset(GroupId(g) for g in x_groups.split(",") if g),
        policy_epoch=x_policy_epoch,
    )


def _unavailable(detail: str) -> JSONResponse:
    # Generic on purpose: epochs and backend names stay in logs, not in responses.
    return JSONResponse(status_code=503, content={"detail": detail}, headers={"Retry-After": "1"})


def create_app(
    service: QueryService,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
    *,
    answers: AnswerService | None = None,
    identity: Callable[..., Any] | None = None,
    stats: StageStats | None = None,
) -> FastAPI:
    app = FastAPI(title="RAG", lifespan=lifespan)
    collector = stats if stats is not None else StageStats()
    ctx_dep: Callable[..., Any] = identity if identity is not None else get_security_context

    @app.exception_handler(AuthzUnavailable)
    async def authz_unavailable(request: Request, exc: AuthzUnavailable) -> JSONResponse:
        return _unavailable("authorization state unavailable, retry shortly")

    @app.exception_handler(RetrievalUnavailable)
    async def retrieval_unavailable(request: Request, exc: RetrievalUnavailable) -> JSONResponse:
        return _unavailable("search backends unavailable, retry shortly")

    @app.exception_handler(StateUnavailable)
    async def state_unavailable(request: Request, exc: StateUnavailable) -> JSONResponse:
        return _unavailable("document state unavailable, retry shortly")

    @app.middleware("http")
    async def timing(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        trace, token = start_trace()
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            finish_trace(token)
        total = (time.perf_counter() - started) * 1000
        parts = [f"{name};dur={ms:.1f}" for name, ms in trace.stages.items()]
        parts.append(f"total;dur={total:.1f}")
        response.headers["Server-Timing"] = ", ".join(parts)
        if request.url.path in ("/search", "/ask"):
            collector.record(request.url.path, response.status_code, total, trace.stages)
        return response

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/stats")
    async def get_stats() -> dict[str, object]:
        return collector.snapshot()

    @app.post("/search", response_model=SearchResponse)
    async def search(
        body: SearchRequest,
        ctx: Annotated[SecurityContext, Depends(ctx_dep)],
    ) -> SearchResponse:
        hits = await service.retrieve(ctx, body.query, body.top_k)
        return SearchResponse(
            hits=[
                HitOut(
                    chunk_id=h.chunk_id,
                    document_id=h.document_id,
                    version=h.version,
                    title=h.title,
                    section=h.section,
                    start_offset=h.start_offset,
                    end_offset=h.end_offset,
                    text=h.text,
                    score=h.score,
                )
                for h in hits
            ]
        )

    if answers is not None:

        @app.post("/ask", response_model=AskResponse)
        async def ask(
            body: AskRequest,
            ctx: Annotated[SecurityContext, Depends(ctx_dep)],
        ) -> AskResponse:
            result = await answers.ask(ctx, body.question, body.top_k)
            return AskResponse(
                answer=result.text,
                grounded=result.grounded,
                degraded=list(result.degraded),
                citations=[
                    CitationOut(
                        marker=c.marker,
                        chunk_id=c.chunk_id,
                        document_id=c.document_id,
                        version=c.version,
                        title=c.title,
                        section=c.section,
                        start_offset=c.start_offset,
                        end_offset=c.end_offset,
                    )
                    for c in result.citations
                ],
            )

    return app


