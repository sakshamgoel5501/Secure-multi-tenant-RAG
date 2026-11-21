from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from domain.ops_ports import AuditEntry


class InMemoryAuditLog:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []
        self.fail = False  # tests flip this to simulate an outage

    async def record(self, entry: AuditEntry) -> None:
        if self.fail:
            raise ConnectionError("audit store down")
        self.entries.append(replace(entry, at=datetime.now(UTC).isoformat()))

    async def list_entries(self, tenant: str | None, limit: int) -> list[AuditEntry]:
        rows = [e for e in reversed(self.entries) if tenant is None or e.tenant == tenant]
        return rows[:limit]
    

    