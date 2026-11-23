from __future__ import annotations

import argparse
import asyncio
import os

from qdrant_client import AsyncQdrantClient

from adapters.fastembed_embedder import DEFAULT_DIM, DEFAULT_MODEL, model_version_for
from adapters.qdrant_stores import QdrantLexicalStore, QdrantVectorStore
from adapters.tenant_layout import TenantLayout
from adapters.tenant_migration import move_tenant_points


async def run(tenant: str, direction: str) -> None:
    client = (
        AsyncQdrantClient(url=os.environ["QDRANT_URL"])
        if os.environ.get("QDRANT_URL")
        else AsyncQdrantClient(path="./qdrant_data")
    )
    version = model_version_for(DEFAULT_MODEL)
    pool, silo = TenantLayout(version, ()), TenantLayout(version, {tenant})
    src, dst = (pool, silo) if direction == "silo" else (silo, pool)

    await QdrantVectorStore(client, version, DEFAULT_DIM, prefix=dst.prefix(tenant)).ensure()
    await QdrantLexicalStore(client, prefix=dst.prefix(tenant)).ensure()
    for name, s, d in (
        ("dense", src.dense_collection(tenant), dst.dense_collection(tenant)),
        ("lexical", src.lexical_collection(tenant), dst.lexical_collection(tenant)),
    ):
        copied, held = await move_tenant_points(client, s, d, tenant)
        print(f"{name}: moved {copied} points ({held} in the source) from {s} to {d}")
    await client.close()
    where = "RAG_SILO_TENANTS (add it)" if direction == "silo" else "RAG_SILO_TENANTS (remove it)"
    print(f"\ndone. Now restart the server with {where} for {tenant}.")


def main() -> None:
    p = argparse.ArgumentParser(description="Move a tenant between the shared pool and its own collections")
    p.add_argument("--tenant", required=True)
    p.add_argument("--to", choices=("silo", "pool"), required=True)
    args = p.parse_args()
    asyncio.run(run(args.tenant, args.to))


if __name__ == "__main__":
    main()

    