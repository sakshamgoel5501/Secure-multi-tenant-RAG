from __future__ import annotations

import hashlib
from collections.abc import Sequence


class HashEmbedder:
    """
    Fake embedder: same text always gives the same 8-dim unit-ish vector.

    A deterministic hash-based embedder, so tests are repeatable with no model download.
    """

    def __init__(self, model_version: str = "hash-v1") -> None:
        self._model_version = model_version

    @property
    def model_version(self) -> str:
        return self._model_version

    async def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        out: list[tuple[float, ...]] = []
        for t in texts:
            digest = hashlib.sha256(t.encode()).digest()
            out.append(tuple(b / 255.0 for b in digest[:8]))
        return out
    


