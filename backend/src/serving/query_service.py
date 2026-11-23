from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

from domain.errors import RetrievalUnavailable, StateUnavailable
from domain.fusion import reciprocal_rank_fusion
from domain.models import SearchHit, SecurityContext
from domain.ports import (
    AclReader,
    DocStateStore,
    Embedder,
    LexicalStore,
    Reranker,
    VectorStore,
)
from domain.tracing import span


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    hits: list[SearchHit]
    degraded: tuple[str, ...]  # stages that failed or timed out
    queries: tuple[str, ...] = ()  # sub-questions searched, when the question was split


class Retriever(Protocol):
    async def retrieve_ex(self, ctx: SecurityContext, query: str, top_k: int) -> RetrievalResult: ...


class QueryService:
    def __init__(
        self,
        doc_state: DocStateStore,
        vectors: VectorStore,
        embedder: Embedder,
        acl: AclReader,
        *,
        lexical: LexicalStore | None = None,
        reranker: Reranker | None = None,
        overfetch: int = 3,
        candidate_k: int = 40,
        max_candidates: int = 400,
        growth: int = 4,
        rerank_k: int = 20,
        retrieval_timeout: float = 0.4,
        rerank_timeout: float = 0.3,
    ) -> None:
        self._state = doc_state
        self._vectors = vectors
        self._embedder = embedder
        self._acl = acl
        self._lexical = lexical
        self._reranker = reranker
        self._overfetch = overfetch
        self._candidate_k = candidate_k
        self._max_candidates = max_candidates
        self._growth = max(2, growth)
        self._rerank_k = rerank_k
        self._retrieval_timeout = retrieval_timeout
        self._rerank_timeout = rerank_timeout

    async def retrieve(self, ctx: SecurityContext, query: str, top_k: int) -> list[SearchHit]:
        return (await self.retrieve_ex(ctx, query, top_k)).hits

    async def retrieve_ex(self, ctx: SecurityContext, query: str, top_k: int) -> RetrievalResult:
        degraded: list[str] = []

        def note(names: list[str]) -> None:
            degraded.extend(n for n in names if n not in degraded)

        n = max(self._candidate_k, top_k * self._overfetch)
        allowed, saturated, failed = await self._authorized(ctx, query, n)
        note(failed)

        # Version and ACL checks can discard most candidates for a user who may read few documents.
        # If the search was cut off at `n`, look further down the ranking, up to a cap. The checks
        # run again each round against live state, so nothing here relies on copied permissions.
        while len(allowed) < top_k and saturated and n < self._max_candidates:
            n = min(n * self._growth, self._max_candidates)
            allowed, saturated, failed = await self._authorized(ctx, query, n)
            note(failed)

        # Rerank only authorized hits. If the reranker is slow or down, keep fused order.
        if self._reranker is not None and allowed:
            try:
                with span("rerank"):
                    reranked = await asyncio.wait_for(
                        self._reranker.rerank(query, allowed[: self._rerank_k], top_k),
                        self._rerank_timeout,
                    )
                return RetrievalResult(reranked[:top_k], tuple(degraded))
            except Exception:  # noqa: BLE001
                note(["reranker"])

        return RetrievalResult(allowed[:top_k], tuple(degraded))

    async def _authorized(
        self, ctx: SecurityContext, query: str, n: int
    ) -> tuple[list[SearchHit], bool, list[str]]:
        """One round: retrieve `n` candidates, then keep only those the caller may see.
        Returns (authorized hits, whether any retriever filled its quota, failed retrievers)."""
        failed: list[str] = []

        # 1. Dense and lexical retrieval run in parallel, each with its own timeout.
        calls = [self._guard("dense", self._dense(ctx, query, n), failed)]
        if self._lexical is not None:
            calls.append(self._guard("lexical", self._lex(self._lexical, ctx, query, n), failed))
        rankings = await asyncio.gather(*calls)
        if len(failed) == len(calls):
            raise RetrievalUnavailable("all retrievers failed: " + ", ".join(failed))

        saturated = any(len(r) >= n for r in rankings)
        non_empty = [r for r in rankings if r]
        if not non_empty:
            return [], False, failed

        with span("fuse"):
            candidates = non_empty[0] if len(non_empty) == 1 else reciprocal_rank_fusion(non_empty)
            # 2. Never trust the store for tenant isolation.
            candidates = [h for h in candidates if h.tenant_id == ctx.tenant_id]

        # 3. The commit point decides which version is visible (hides orphans and deletes).
        #    If it can't be read, visibility can't be verified: fail closed.
        try:
            with span("state"):
                states = await self._state.get_many(
                    ctx.tenant_id, {h.document_id for h in candidates}
                )
        except Exception as exc:
            raise StateUnavailable(f"document state unavailable: {exc!r}") from exc
        visible = [
            h
            for h in candidates
            if (s := states.get(h.document_id)) is not None
            and s.is_searchable
            and s.active_version == h.version
        ]
        if not visible:
            return [], saturated, failed

        # 4. Authoritative ACL check. Raises AuthzUnavailable, so the request fails closed.
        with span("acl"):
            snapshot = await self._acl.acls_for(
                ctx.tenant_id, {h.document_id for h in visible}, min_epoch=ctx.policy_epoch
            )
        allowed = [
            h for h in visible if snapshot.acls.get(h.document_id, frozenset()) & ctx.group_ids
        ]
        return allowed, saturated, failed

    async def _dense(self, ctx: SecurityContext, query: str, n: int) -> list[SearchHit]:
        with span("embed"):
            [query_vector] = await self._embedder.embed([query])
        with span("dense"):
            return await self._vectors.search(ctx, query_vector, n)

    @staticmethod
    async def _lex(
        lexical: LexicalStore, ctx: SecurityContext, query: str, n: int
    ) -> list[SearchHit]:
        with span("lexical"):
            return await lexical.search(ctx, query, n)

    async def _guard(
        self, name: str, call: Awaitable[list[SearchHit]], failed: list[str]
    ) -> list[SearchHit]:
        try:
            return await asyncio.wait_for(call, self._retrieval_timeout)
        except Exception:  # noqa: BLE001
            failed.append(name)
            return []
        

        