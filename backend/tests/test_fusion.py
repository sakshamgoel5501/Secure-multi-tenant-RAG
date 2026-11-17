from domain.fusion import reciprocal_rank_fusion
from domain.models import (
    ChunkId,
    DocumentId,
    RetrievalSource,
    SearchHit,
    TenantId,
)


def hit(cid: str, score: float, source: RetrievalSource) -> SearchHit:
    return SearchHit(
        chunk_id=ChunkId(cid),
        tenant_id=TenantId("t1"),
        document_id=DocumentId(cid),
        version=1,
        title=cid,
        section=None,
        start_offset=0,
        end_offset=1,
        text=cid,
        score=score,
        source=source,
    )


D = RetrievalSource.DENSE
L = RetrievalSource.LEXICAL


def test_chunk_found_by_both_retrievers_ranks_first() -> None:
    dense = [hit("x", 0.9, D), hit("y", 0.8, D)]
    lexical = [hit("z", 7.0, L), hit("x", 5.0, L)]
    fused = reciprocal_rank_fusion([dense, lexical])
    assert fused[0].chunk_id == "x"  # rank 1 + rank 2 beats a single rank 1


def test_raw_scores_are_ignored_only_ranks_matter() -> None:
    dense = [hit("a", 0.0001, D), hit("b", 0.00001, D)]
    lexical = [hit("b", 9999.0, L), hit("a", 1.0, L)]
    fused = reciprocal_rank_fusion([dense, lexical])
    assert {h.chunk_id for h in fused} == {"a", "b"}
    assert fused[0].score == fused[1].score  # symmetric ranks give a tie


def test_each_chunk_appears_once_and_is_marked_hybrid() -> None:
    fused = reciprocal_rank_fusion([[hit("x", 1.0, D)], [hit("x", 2.0, L)]])
    assert len(fused) == 1
    assert fused[0].source is RetrievalSource.HYBRID


def test_single_ranking_keeps_its_order() -> None:
    ranking = [hit("a", 3.0, D), hit("b", 2.0, D), hit("c", 1.0, D)]
    assert [h.chunk_id for h in reciprocal_rank_fusion([ranking])] == ["a", "b", "c"]


def test_empty_input_gives_empty_output() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []




    