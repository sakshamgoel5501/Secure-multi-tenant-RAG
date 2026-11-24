from __future__ import annotations

import asyncio
import os
from pathlib import Path

from adapters.encrypted_blobs import EncryptedBlobStore
from adapters.local_blobs import LocalBlobStore
from domain.models import DocumentId, TenantId


async def run(root: Path, keys: list[str]) -> None:
    inner = LocalBlobStore(root)
    sealed = EncryptedBlobStore(inner, keys, allow_plaintext=True)
    done = skipped = 0
    for tenant_dir in sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []:
        for doc_dir in sorted(p for p in tenant_dir.iterdir() if p.is_dir()):
            t, d = TenantId(tenant_dir.name), DocumentId(doc_dir.name)
            for blob in await inner.list_blobs(t, d):
                raw = await inner.get(t, d, blob.version, blob.kind)
                if raw is None:
                    continue
                if sealed.is_encrypted(raw):
                    skipped += 1
                    continue
                await sealed.put(t, d, blob.version, blob.kind, raw)
                done += 1
    print(f"encrypted {done} files, {skipped} were already encrypted")


def main() -> None:
    keys = [k.strip() for k in os.environ.get("RAG_BLOB_KEY", "").split(",") if k.strip()]
    if not keys:
        raise SystemExit("set RAG_BLOB_KEY first")
    asyncio.run(run(Path(os.environ.get("RAG_BLOB_DIR", "data/blobs")), keys))


if __name__ == "__main__":
    main()

    