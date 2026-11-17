import math
import os

import pytest

from adapters.fastembed_embedder import FastEmbedEmbedder
from adapters.fastembed_reranker import FastEmbedReranker
from domain.models import (
    ChunkId,
    DocumentId,
    RetrievalSource,
    SearchHit,
    TenantId,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RAG_RUN_MODEL_TESTS") != "1", reason="set RAG_RUN_MODEL_TESTS=1"
)


def cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


async def test_embedder_understands_synonyms() -> None:
    e = FastEmbedEmbedder()
    q, leave, menu = await e.embed(
        [
            "how many vacation days do I get",
            "Employees receive 20 days of paid leave",
            "The cafeteria menu changes weekly",
        ]
    )
    assert len(q) == e.dim
    assert cosine(q, leave) > cosine(q, menu)  # no shared words, same meaning


def hit(cid: str, text: str) -> SearchHit:
    return SearchHit(
        ChunkId(cid), TenantId("t1"), DocumentId(cid), 1, cid, None, 0, len(text), text,
        0.0, RetrievalSource.HYBRID,
    )


async def test_reranker_puts_relevant_passage_first() -> None:
    r = FastEmbedReranker()
    hits = [
        hit("menu", "The cafeteria menu changes weekly."),
        hit("leave", "Employees receive 20 days of paid leave per year."),
    ]
    ranked = await r.rerank("how many vacation days do employees get", hits, top_k=2)
    assert ranked[0].document_id == "leave"


    