# A fake cross-encoder that scores by query-term overlap. The real one (bge-reranker) comes with the real adapters.

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace

from domain.models import SearchHit

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


class OverlapReranker:
    async def rerank(
        self, query: str, hits: Sequence[SearchHit], top_k: int
    ) -> list[SearchHit]:
        q = _tokens(query)

        def score(h: SearchHit) -> float:
            return len(q & _tokens(h.text)) / len(q) if q else 0.0

        ranked = sorted(hits, key=score, reverse=True)  # stable: ties keep fused order
        return [replace(h, score=score(h)) for h in ranked[:top_k]]
    





