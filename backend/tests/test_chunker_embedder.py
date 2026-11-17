from adapters.fake_embedder import HashEmbedder
from adapters.simple_chunker import ParagraphChunker
from domain.models import DocumentId, TenantId
from domain.ports import Chunker, Embedder

T = TenantId("t1")
D = DocumentId("d1")


def make_chunker(max_chars: int = 30) -> Chunker:
    return ParagraphChunker(max_chars)


def test_chunk_offsets_point_back_into_source() -> None:
    text = "alpha beta\n\ngamma delta\n\nepsilon"
    for c in make_chunker(15).chunk(T, D, 1, "doc", text):
        assert text[c.start_offset : c.end_offset] == c.text


def test_chunk_ids_are_deterministic() -> None:
    text = "one\n\ntwo\n\nthree"
    a = make_chunker(5).chunk(T, D, 2, "doc", text)
    b = make_chunker(5).chunk(T, D, 2, "doc", text)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert a[0].chunk_id == "d1:2:0"


def test_small_paragraphs_are_packed_together() -> None:
    chunks = make_chunker(100).chunk(T, D, 1, "doc", "aaa\n\nbbb\n\nccc")
    assert len(chunks) == 1


def test_empty_text_gives_no_chunks() -> None:
    assert make_chunker().chunk(T, D, 1, "doc", "  \n\n ") == []


async def test_embedder_is_deterministic() -> None:
    e: Embedder = HashEmbedder()
    a = await e.embed(["hello", "world"])
    b = await e.embed(["hello", "world"])
    assert a == b
    assert a[0] != a[1]


    