from __future__ import annotations

import asyncio
import logging

from domain.errors import AuthzUnavailable, RetrievalUnavailable, StateUnavailable
from domain.fusion import interleave
from domain.models import SearchHit, SecurityContext
from domain.ports import Decomposer
from domain.router import Route, classify
from domain.tracing import span
from serving.query_service import RetrievalResult, Retriever

log = logging.getLogger("rag.planner")


class PlannedRetriever:
    """Wraps a retriever. Simple questions go straight through. Multi-part ones are split, each
    part is retrieved through the full authorized path in parallel, and the results are merged.
    Anything that goes wrong before retrieval falls back to the original question."""

    def __init__(
        self, inner: Retriever, decomposer: Decomposer, *, timeout: float = 2.0, max_parts: int = 3
    ) -> None:
        self._inner = inner
        self._decomposer = decomposer
        self._timeout = timeout
        self._max_parts = max_parts

    async def retrieve_ex(self, ctx: SecurityContext, query: str, top_k: int) -> RetrievalResult:
        if classify(query) is Route.SIMPLE:
            return await self._inner.retrieve_ex(ctx, query, top_k)

        try:
            with span("decompose"):
                parts = await asyncio.wait_for(self._decomposer.decompose(query), self._timeout)
        except Exception:
            log.warning("decomposition failed; using the original question", exc_info=True)
            single = await self._inner.retrieve_ex(ctx, query, top_k)
            return RetrievalResult(single.hits, (*single.degraded, "decompose"), single.queries)

        parts = list(dict.fromkeys(p.strip() for p in parts if p.strip()))[: self._max_parts]
        if len(parts) < 2:
            return await self._inner.retrieve_ex(ctx, query, top_k)

        results = await asyncio.gather(
            *(self._inner.retrieve_ex(ctx, p, top_k) for p in parts), return_exceptions=True
        )
        ok: list[RetrievalResult] = []
        failures: list[BaseException] = []
        for outcome in results:
            if isinstance(outcome, RetrievalResult):
                ok.append(outcome)
            else:
                failures.append(outcome)
        # A permission or commit-point failure in any part fails the whole request closed.
        for failure in failures:
            if isinstance(failure, (AuthzUnavailable, StateUnavailable)):
                raise failure
        if not ok:
            raise failures[0] if failures else RetrievalUnavailable("no sub-query succeeded")

        degraded = list(dict.fromkeys(d for r in ok for d in r.degraded))
        if failures:
            degraded.append("subquery")
        merged: list[SearchHit] = interleave([r.hits for r in ok], top_k)
        return RetrievalResult(merged, tuple(degraded), tuple(parts))
    
    