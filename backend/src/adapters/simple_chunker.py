from __future__ import annotations

from domain.models import Chunk, DocumentId, TenantId, make_chunk_id


class ParagraphChunker:
    """Splits on blank lines and packs paragraphs up to max_chars per chunk."""

    def __init__(self, max_chars: int = 800) -> None:
        self._max_chars = max_chars

    def chunk(
        self,
        tenant_id: TenantId,
        document_id: DocumentId,
        version: int,
        title: str,
        text: str,
    ) -> list[Chunk]:
        spans: list[tuple[int, int]] = []  # (start, end) offsets into text
        pos = 0
        for para in text.split("\n\n"):
            start = text.index(para, pos) if para else pos
            end = start + len(para)
            pos = end
            if not para.strip():
                continue
            if spans and end - spans[-1][0] <= self._max_chars:
                spans[-1] = (spans[-1][0], end)  # merge into previous chunk
            else:
                spans.append((start, end))

        return [
            Chunk(
                chunk_id=make_chunk_id(document_id, version, i),
                tenant_id=tenant_id,
                document_id=document_id,
                version=version,
                ordinal=i,
                text=text[s:e],
                title=title,
                section=None,
                start_offset=s,
                end_offset=e,
            )
            for i, (s, e) in enumerate(spans)
        ]
    


    