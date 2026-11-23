from __future__ import annotations

import asyncio
import os
import re
import shutil
from pathlib import Path

from domain.models import DocumentId, TenantId
from domain.ops_ports import BlobInfo

_SAFE = re.compile(r"^[\w-]{1,64}$")
_KINDS = frozenset({"original", "text", "meta"})
_NAME = re.compile(r"^v(\d+)\.(original|text|meta)$")


class LocalBlobStore:
    """Files on local disk: <root>/<tenant>/<document>/v<version>.<kind>. A cloud bucket is the
    production adapter behind the same port. Ids are validated so a name can't escape the root, and
    writes go through a temporary file so a crash never leaves half a file under the real name."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _dir(self, tenant: str, document: str) -> Path:
        for part in (tenant, document):
            if not _SAFE.match(part):
                raise ValueError(f"invalid id: {part!r}")
        return self._root / tenant / document

    @staticmethod
    def _name(version: int, kind: str) -> str:
        if kind not in _KINDS or version < 0:
            raise ValueError("invalid blob key")
        return f"v{version}.{kind}"

    async def put(self, tenant_id: TenantId, document_id: DocumentId, version: int, kind: str, data: bytes) -> None:
        directory, name = self._dir(tenant_id, document_id), self._name(version, kind)

        def write() -> None:
            directory.mkdir(parents=True, exist_ok=True)
            tmp = directory / f".{name}.tmp"
            tmp.write_bytes(data)
            os.replace(tmp, directory / name)

        await asyncio.to_thread(write)

    async def get(self, tenant_id: TenantId, document_id: DocumentId, version: int, kind: str) -> bytes | None:
        path = self._dir(tenant_id, document_id) / self._name(version, kind)

        def read() -> bytes | None:
            return path.read_bytes() if path.is_file() else None

        return await asyncio.to_thread(read)

    async def list_blobs(self, tenant_id: TenantId, document_id: DocumentId) -> list[BlobInfo]:
        directory = self._dir(tenant_id, document_id)

        def scan() -> list[BlobInfo]:
            if not directory.is_dir():
                return []
            found = []
            for p in directory.iterdir():
                m = _NAME.match(p.name)
                if m and p.is_file():
                    found.append(BlobInfo(int(m.group(1)), m.group(2), p.stat().st_size))
            return sorted(found, key=lambda b: (b.version, b.kind))

        return await asyncio.to_thread(scan)

    async def delete_document(self, tenant_id: TenantId, document_id: DocumentId) -> int:
        directory = self._dir(tenant_id, document_id)

        def remove() -> int:
            if not directory.is_dir():
                return 0
            count = sum(1 for p in directory.iterdir() if p.is_file())
            shutil.rmtree(directory)
            return count

        return await asyncio.to_thread(remove)
    

    