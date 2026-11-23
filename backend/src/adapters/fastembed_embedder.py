from __future__ import annotations

import asyncio
from collections.abc import Sequence

from fastembed import TextEmbedding

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_DIM = 384


def model_version_for(model_name: str) -> str:
    return f"fastembed-{model_name.split('/')[-1]}"


class FastEmbedEmbedder:
    """Local ONNX embeddings (CPU). Inference runs in a thread so it never blocks the event loop."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        dim: int = DEFAULT_DIM,
        cache_dir: str = ".model_cache",
    ) -> None:
        self._model_name = model_name
        self._dim = dim
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)

    @property
    def model_version(self) -> str:
        return model_version_for(self._model_name)

    @property
    def dim(self) -> int:
        return self._dim

    async def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        vectors = await asyncio.to_thread(self._embed_sync, list(texts))
        if vectors and len(vectors[0]) != self._dim:
            raise ValueError(f"expected {self._dim} dims, model returned {len(vectors[0])}")
        return vectors

    def _embed_sync(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [tuple(float(x) for x in v) for v in self._model.embed(texts)]
    

    