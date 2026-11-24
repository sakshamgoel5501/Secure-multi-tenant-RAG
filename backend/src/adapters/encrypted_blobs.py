from __future__ import annotations

import asyncio
from collections.abc import Sequence

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from domain.models import DocumentId, TenantId
from domain.ops_ports import BlobInfo, BlobStore


class EncryptedBlobStore:
    """Wraps any BlobStore. Contents are encrypted with the first key and readable with any listed
    key. The location is sealed inside the ciphertext, so a file copied to another document fails to
    open. With allow_plaintext, unencrypted files still read (for migration); turn it off after
    running `rag encrypt-blobs`."""

    def __init__(self, inner: BlobStore, keys: Sequence[str], *, allow_plaintext: bool = False) -> None:
        if not keys:
            raise ValueError("at least one key is required")
        self._inner = inner
        self._fernet = MultiFernet([Fernet(k) for k in keys])
        self._allow_plaintext = allow_plaintext

    @staticmethod
    def _header(tenant: str, document: str, version: int, kind: str) -> bytes:
        return f"{tenant}\x1f{document}\x1f{version}\x1f{kind}".encode()

    def is_encrypted(self, raw: bytes) -> bool:
        try:
            self._fernet.decrypt(raw)
        except InvalidToken:
            return False
        return True

    async def put(self, tenant_id: TenantId, document_id: DocumentId, version: int, kind: str, data: bytes) -> None:
        sealed = await asyncio.to_thread(
            self._fernet.encrypt, self._header(tenant_id, document_id, version, kind) + b"\x1e" + data
        )
        await self._inner.put(tenant_id, document_id, version, kind, sealed)

    async def get(self, tenant_id: TenantId, document_id: DocumentId, version: int, kind: str) -> bytes | None:
        raw = await self._inner.get(tenant_id, document_id, version, kind)
        if raw is None:
            return None
        try:
            plain = await asyncio.to_thread(self._fernet.decrypt, raw)
        except InvalidToken:
            if self._allow_plaintext:
                return raw
            raise
        header, sep, body = plain.partition(b"\x1e")
        if not sep or header != self._header(tenant_id, document_id, version, kind):
            raise ValueError("stored file does not belong at this location")
        return body

    async def list_blobs(self, tenant_id: TenantId, document_id: DocumentId) -> list[BlobInfo]:
        return await self._inner.list_blobs(tenant_id, document_id)

    async def delete_document(self, tenant_id: TenantId, document_id: DocumentId) -> int:
        return await self._inner.delete_document(tenant_id, document_id)
    

    