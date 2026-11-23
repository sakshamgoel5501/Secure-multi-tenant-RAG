from __future__ import annotations

from typing import Any

from qdrant_client import AsyncQdrantClient, models


async def move_tenant_points(
    client: AsyncQdrantClient, source: str, target: str, tenant: str, *, batch: int = 200
) -> tuple[int, int]:
    """Copies one tenant's points from one collection to another, checks that every point arrived,
    and only then deletes them from the source. Safe to re-run: point ids are unchanged, so a second
    run overwrites with identical data. Returns (points copied, points the source held)."""
    if not await client.collection_exists(source):
        return 0, 0
    flt = models.Filter(
        must=[models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant))]
    )
    copied = 0
    offset: Any = None
    while True:
        points, offset = await client.scroll(
            collection_name=source, scroll_filter=flt, limit=batch, offset=offset,
            with_payload=True, with_vectors=True,
        )  # fmt: skip
        if points:
            vectors: Any = [p.vector for p in points]
            await client.upsert(
                collection_name=target,
                points=[
                    models.PointStruct(id=p.id, vector=v, payload=p.payload)
                    for p, v in zip(points, vectors, strict=True)
                ],
                wait=True,
            )
            copied += len(points)
        if offset is None:
            break
    expected = (await client.count(collection_name=source, count_filter=flt, exact=True)).count
    present = (await client.count(collection_name=target, count_filter=flt, exact=True)).count
    if present < expected:
        raise RuntimeError(f"only {present} of {expected} points reached {target}; source left untouched")
    if expected:
        await client.delete(
            collection_name=source, points_selector=models.FilterSelector(filter=flt), wait=True
        )
    return copied, expected

