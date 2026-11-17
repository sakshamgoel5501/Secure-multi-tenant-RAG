from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from domain.models import ChunkId, RetrievalSource, SearchHit


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[SearchHit]], *, k: int = 60
) -> list[SearchHit]:
    """Merge ranked lists using ranks only. k=60 is the value from the original paper;
    larger k flattens the difference between top and lower ranks."""
    scores: dict[ChunkId, float] = {}
    first_seen: dict[ChunkId, SearchHit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
            first_seen.setdefault(hit.chunk_id, hit)

    ordered = sorted(scores, key=lambda cid: scores[cid], reverse=True)
    return [
        replace(first_seen[cid], score=scores[cid], source=RetrievalSource.HYBRID)
        for cid in ordered
    ]



