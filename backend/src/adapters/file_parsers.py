from __future__ import annotations

import io
import logging
import re
import zipfile

from pypdf import PdfReader

from domain.errors import FileRejected
from domain.models import ParsedFile

log = logging.getLogger("rag.files")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", _CONTROL.sub("", text)).strip()


class DefaultFileParser:
    """PDF, DOCX and UTF-8 text. The type comes from the content. Everything is bounded: bytes,
    pages, unzipped size, member count and extracted characters. It does NOT run OCR, so a scanned
    PDF is rejected, and it extracts all text a file contains, including text a viewer wouldn't
    show (white-on-white, tiny fonts). Downstream defenses treat every source as untrusted data."""

    def __init__(
        self,
        *,
        max_text: int = 200_000,
        max_pages: int = 300,
        max_unzipped: int = 50_000_000,
        max_members: int = 2000,
    ) -> None:
        self._max_text = max_text
        self._max_pages = max_pages
        self._max_unzipped = max_unzipped
        self._max_members = max_members

    def parse(self, data: bytes) -> ParsedFile:
        if data.startswith(b"%PDF-"):
            kind, raw = "pdf", self._pdf(data)
        elif data.startswith(b"PK\x03\x04"):
            kind, raw = "docx", self._docx(data)
        else:
            kind, raw = "text", self._plain(data)
        text = _clean(raw)
        if not text:
            raise FileRejected("the file has no readable text")
        if len(text) > self._max_text:
            raise FileRejected(f"the text is {len(text):,} characters; the limit is {self._max_text:,}")
        return ParsedFile(text, kind)

    @staticmethod
    def _plain(data: bytes) -> str:
        if b"\x00" in data[:8192]:
            raise FileRejected("this looks like a binary file; use PDF, DOCX, TXT or Markdown")
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise FileRejected("text files must be UTF-8") from None

    def _pdf(self, data: bytes) -> str:
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise FileRejected("encrypted PDFs aren't supported")
            if len(reader.pages) > self._max_pages:
                raise FileRejected(f"the PDF has {len(reader.pages)} pages; the limit is {self._max_pages}")
            parts: list[str] = []
            total = 0
            for page in reader.pages:
                text = (page.extract_text() or "").strip()
                if text:
                    parts.append(text)
                    total += len(text)
                if total > self._max_text:
                    break  # parse() reports the length
        except FileRejected:
            raise
        except Exception:  # noqa: BLE001
            log.warning("pdf could not be read", exc_info=True)
            raise FileRejected("the PDF could not be read") from None
        if not parts:
            raise FileRejected("the PDF has no extractable text (scanned PDFs need OCR, which isn't supported)")
        return "\n\n".join(parts)

    def _docx(self, data: bytes) -> str:
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise FileRejected("the file is not a valid DOCX") from None
        members = archive.infolist()
        if len(members) > self._max_members:
            raise FileRejected("the document has too many parts")
        total = 0
        for m in members:
            total += m.file_size  # reads are capped at the declared size, so this can't be lied about
            if total > self._max_unzipped:
                raise FileRejected("the document expands to too much data")
            if m.compress_size and m.file_size > 1_000_000 and m.file_size / m.compress_size > 200:
                raise FileRejected("the document is compressed suspiciously well")
        if "word/document.xml" not in archive.namelist():
            raise FileRejected("this zip file is not a Word document")
        try:
            from docx import Document

            doc = Document(io.BytesIO(data))
            parts = [p.text for p in doc.paragraphs if p.text.strip()]
            for table in doc.tables:
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    if any(cells):
                        parts.append(" | ".join(cells))
        except Exception:  # noqa: BLE001
            log.warning("docx could not be read", exc_info=True)
            raise FileRejected("the Word document could not be read") from None
        return "\n\n".join(parts)
    
    