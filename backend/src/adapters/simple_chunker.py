from __future__ import annotations

from domain.models import Chunk, DocumentId, TenantId, make_chunk_id


class ParagraphChunker:
    """Splits on blank lines and packs paragraphs up to max_chars per chunk. A paragraph longer than
    max_chars is split at whitespace, so nothing exceeds what the embedder can read."""

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
            for s, e in self._pieces(text, start, end):
                if spans and e - spans[-1][0] <= self._max_chars:
                    spans[-1] = (spans[-1][0], e)  # merge into previous chunk
                else:
                    spans.append((s, e))

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

    def _pieces(self, text: str, start: int, end: int) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        pos = start
        while end - pos > self._max_chars:
            window = pos + self._max_chars
            cut = max(text.rfind("\n", pos + self._max_chars // 2, window), text.rfind(" ", pos + self._max_chars // 2, window))
            if cut <= pos:
                cut = max(text.rfind("\n", pos + 1, window), text.rfind(" ", pos + 1, window))
            if cut <= pos:
                cut = window  # no whitespace at all: cut hard
            out.append((pos, cut))
            pos = cut
            while pos < end and text[pos].isspace():
                pos += 1
        if pos < end:
            out.append((pos, end))
        return out
    
    