from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path

from redis.asyncio import Redis

from adapters.postgres_acl import PostgresAclStore
from adapters.redis_bus import RedisEventBus
from domain.models import DocumentEvent, Operation
from ingestion.corpus import generate_corpus


async def load(tenants: int, docs: int, seed: int, golden_path: Path) -> None:
    dsn = os.environ.get("RAG_PG_DSN", "postgresql://localhost/rag")
    redis_url = os.environ.get("RAG_REDIS_URL", "redis://localhost:6379/0")
    corpus, golden = generate_corpus(tenants, docs, seed)

    acl = PostgresAclStore(dsn)
    await acl.start()
    redis = Redis.from_url(redis_url, decode_responses=True)
    bus = RedisEventBus(redis)
    await bus.ensure()

    epoch = 0
    for d in corpus:  # ACLs first, so a document is never searchable without its ACL
        epoch = await acl.set_acl(d.tenant_id, d.document_id, d.groups)
    for d in corpus:
        await bus.publish(
            DocumentEvent(Operation.UPSERT, d.tenant_id, d.document_id, 1, d.title, d.text)
        )

    golden_path.parent.mkdir(parents=True, exist_ok=True)
    golden_path.write_text(json.dumps([asdict(g) for g in golden], indent=2))
    await acl.close()
    await redis.aclose()

    print(f"published {len(corpus)} documents across {tenants} tenants; ACL epoch now {epoch}")
    print(f"golden queries written to {golden_path}")
    for g in golden[:3]:
        print(f"  tenant={g.tenant_id} group={g.group_id}  {g.question!r}  -> {g.relevant_doc_id}")


def main() -> None:
    p = argparse.ArgumentParser(description="Load a synthetic multi-tenant corpus")
    p.add_argument("--tenants", type=int, default=3)
    p.add_argument("--docs", type=int, default=40, help="documents per tenant")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--golden", type=Path, default=Path("data/golden.json"))
    args = p.parse_args()
    asyncio.run(load(args.tenants, args.docs, args.seed, args.golden))


if __name__ == "__main__":
    main()


    