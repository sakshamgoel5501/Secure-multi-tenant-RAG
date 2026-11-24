from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from adapters.encrypted_blobs import EncryptedBlobStore
from adapters.local_blobs import LocalBlobStore
from domain.ops_ports import BlobStore


def make_blob_store(root: Path, env: Mapping[str, str]) -> BlobStore:
    """Local files, encrypted when RAG_BLOB_KEY is set (generate one with
    `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)."""
    store = LocalBlobStore(root)
    keys = [k.strip() for k in env.get("RAG_BLOB_KEY", "").split(",") if k.strip()]
    if not keys:
        return store
    return EncryptedBlobStore(store, keys, allow_plaintext=env.get("RAG_BLOB_ALLOW_PLAINTEXT") == "1")

