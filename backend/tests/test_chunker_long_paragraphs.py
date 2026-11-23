from adapters.simple_chunker import ParagraphChunker
from domain.models import DocumentId, TenantId

T, D = TenantId("t1"), DocumentId("d1")


def test_a_long_paragraph_is_split_at_whitespace_within_the_limit() -> None:
    text = " ".join(["word"] * 500)
    chunks = ParagraphChunker(max_chars=100).chunk(T, D, 1, "t", text)
    assert len(chunks) > 10
    assert all(len(c.text) <= 100 for c in chunks)
    assert all(text[c.start_offset : c.end_offset] == c.text for c in chunks)
    assert sum(len(c.text.split()) for c in chunks) == 500  # no word cut in half, none lost


def test_text_without_any_whitespace_is_cut_hard_and_loses_nothing() -> None:
    chunks = ParagraphChunker(max_chars=50).chunk(T, D, 1, "t", "x" * 120)
    assert [len(c.text) for c in chunks] == [50, 50, 20]


def test_short_paragraphs_still_pack_together() -> None:
    assert len(ParagraphChunker(max_chars=100).chunk(T, D, 1, "t", "aaa\n\nbbb\n\nccc")) == 1

    