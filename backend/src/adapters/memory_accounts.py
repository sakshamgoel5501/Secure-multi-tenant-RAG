from __future__ import annotations

from domain.accounts import Account, Role


class InMemoryAccountStore:
    def __init__(self) -> None:
        self._rows: dict[str, Account] = {}

    async def get(self, username: str) -> Account | None:
        return self._rows.get(username)

    async def list_accounts(self, tenant: str | None, limit: int) -> list[Account]:
        rows = sorted(self._rows.values(), key=lambda a: a.username)
        return [a for a in rows if tenant is None or a.tenant == tenant][:limit]

    async def create(self, account: Account) -> bool:
        if account.username in self._rows:
            return False
        self._rows[account.username] = account
        return True

    async def save(self, account: Account) -> None:
        self._rows[account.username] = account

    async def delete(self, username: str) -> bool:
        return self._rows.pop(username, None) is not None

    async def count_active_platform_admins(self) -> int:
        return sum(1 for a in self._rows.values() if a.role is Role.PLATFORM_ADMIN and not a.disabled)
    
    