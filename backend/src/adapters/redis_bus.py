from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from domain.models import DocumentEvent, DocumentId, Operation, TenantId


def encode_event(event: DocumentEvent) -> str:
    return json.dumps(
        {
            "operation": event.operation.value,
            "tenant_id": event.tenant_id,
            "document_id": event.document_id,
            "version": event.version,
            "title": event.title,
            "text": event.text,
        }
    )


def decode_event(raw: str) -> DocumentEvent:
    d = json.loads(raw)
    return DocumentEvent(
        Operation(d["operation"]),
        TenantId(d["tenant_id"]),
        DocumentId(d["document_id"]),
        int(d["version"]),
        str(d.get("title", "")),
        str(d.get("text", "")),
    )


class RedisEventBus:
    """At-least-once event log on Redis Streams.

    A message is delivered to a consumer group member and stays in the group's pending list until
    XACK. If the consumer dies or fails, the message stays pending and can be re-claimed, so
    nothing is lost; the cost is duplicates, which the idempotent worker already tolerates.
    Create the client with decode_responses=True.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        stream: str = "rag:events",
        group: str = "ingest",
        dlq: str = "rag:events:dlq",
    ) -> None:
        self._r = redis
        self._stream = stream
        self._group = group
        self._dlq = dlq

    async def ensure(self) -> None:
        try:
            await self._r.xgroup_create(self._stream, self._group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def publish(self, event: DocumentEvent) -> str:
        return await self.publish_raw(encode_event(event))

    async def publish_raw(self, data: str) -> str:
        return str(await self._r.xadd(self._stream, {"data": data}))

    async def read_new(
        self, consumer: str, *, count: int = 10, block_ms: int | None = None
    ) -> list[tuple[str, str]]:
        res = await self._r.xreadgroup(
            self._group, consumer, {self._stream: ">"}, count=count, block=block_ms
        )
        return _flatten(res)

    async def claim_stale(
        self, consumer: str, min_idle_ms: int, count: int = 10
    ) -> list[tuple[str, str]]:
        """Take over messages that were delivered but never acked (crash, or a failed attempt)."""
        res = await self._r.xautoclaim(
            self._stream,
            self._group,
            consumer,
            min_idle_time=min_idle_ms,
            start_id="0-0",
            count=count,
        )
        entries = res[1] if res else []
        return [(str(i), str((f or {}).get("data", ""))) for i, f in entries]

    async def ack(self, msg_id: str) -> None:
        await self._r.xack(self._stream, self._group, msg_id)

    async def deliveries(self, msg_id: str) -> int:
        info = await self._r.xpending_range(self._stream, self._group, min=msg_id, max=msg_id, count=1)
        return int(info[0]["times_delivered"]) if info else 0

    async def dead_letter(self, msg_id: str, raw: str, error: str, deliveries: int) -> None:
        """Move a poison message to the DLQ and ack it, atomically (MULTI/EXEC)."""
        async with self._r.pipeline(transaction=True) as pipe:
            pipe.xadd(
                self._dlq,
                {
                    "original_id": msg_id,
                    "data": raw,
                    "error": error[:500],
                    "deliveries": str(deliveries),
                },
            )
            pipe.xack(self._stream, self._group, msg_id)
            await pipe.execute()

    async def pending_count(self) -> int:
        info = await self._r.xpending(self._stream, self._group)
        return int(info["pending"])

    async def dlq_entries(self) -> list[dict[str, str]]:
        rows = await self._r.xrange(self._dlq)
        return [dict(fields) for _id, fields in rows]

    async def destroy(self) -> None:
        """Tests only."""
        await self._r.delete(self._stream, self._dlq)

    async def _matching(self, stream: str, tenant_id: str, document_id: str) -> list[str]:
        found: list[str] = []
        start = "-"
        while True:
            rows = await self._r.xrange(stream, min=start, max="+", count=500)
            for entry_id, fields in rows:
                try:
                    data = json.loads(fields.get("data", ""))
                except ValueError:
                    continue
                if (
                    isinstance(data, dict)
                    and data.get("tenant_id") == tenant_id
                    and data.get("document_id") == document_id
                ):
                    found.append(str(entry_id))
            if len(rows) < 500:
                return found
            start = f"({rows[-1][0]}"  # exclusive range: needs Redis 6.2+

    async def count_document_events(self, tenant_id: str, document_id: str) -> int:
        total = 0
        for stream in (self._stream, self._dlq):
            total += len(await self._matching(stream, tenant_id, document_id))
        return total

    async def purge_document_events(self, tenant_id: str, document_id: str) -> int:
        removed = 0
        for stream in (self._stream, self._dlq):
            ids = await self._matching(stream, tenant_id, document_id)
            if ids:
                removed += int(await self._r.xdel(stream, *ids))
        return removed


def _flatten(res: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for _stream, entries in res or []:
        for msg_id, fields in entries:
            out.append((str(msg_id), str((fields or {}).get("data", ""))))
    return out



