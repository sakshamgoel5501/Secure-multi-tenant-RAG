from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace

from fastembed.rerank.cross_encoder import TextCrossEncoder

from domain.models import SearchHit


class FastEmbedReranker:
    """Cross-encoder: reads query and passage together, so it is slower but far more precise
    than the bi-encoder used for retrieval. Only ever called with authorized hits."""

    def __init__(
        self,
        model_name: str = "Xenova/ms-marco-MiniLM-L-6-v2",
        cache_dir: str = ".model_cache",
    ) -> None:
        # If the name is rejected: print(TextCrossEncoder.list_supported_models())
        self._model = TextCrossEncoder(model_name=model_name, cache_dir=cache_dir)

    async def warm_up(self) -> None:
        await asyncio.to_thread(self._score, "warm up", ["warm up"])

    async def rerank(self, query: str, hits: Sequence[SearchHit], top_k: int) -> list[SearchHit]:
        if not hits:
            return []
        scores = await asyncio.to_thread(self._score, query, [h.text for h in hits])
        ranked = sorted(zip(hits, scores, strict=True), key=lambda pair: pair[1], reverse=True)
        return [replace(h, score=s) for h, s in ranked[:top_k]]

    def _score(self, query: str, docs: list[str]) -> list[float]:
        return [float(s) for s in self._model.rerank(query, docs)]
    


    