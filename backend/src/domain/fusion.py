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


def interleave(rankings: Sequence[Sequence[SearchHit]], limit: int) -> list[SearchHit]:
    """Round-robin merge: each ranking contributes its best hits in turn, so every sub-question
    stays represented. Duplicates are dropped. Unlike RRF this doesn't reward a chunk for being
    relevant to several sub-questions, which is the wrong goal when they ask different things."""
    seen: set[ChunkId] = set()
    out: list[SearchHit] = []
    depth = max((len(r) for r in rankings), default=0)
    for position in range(depth):
        for ranking in rankings:
            if position < len(ranking) and ranking[position].chunk_id not in seen:
                seen.add(ranking[position].chunk_id)
                out.append(ranking[position])
                if len(out) >= limit:
                    return out
    return out



