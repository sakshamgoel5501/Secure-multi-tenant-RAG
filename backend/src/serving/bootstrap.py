from __future__ import annotations

import asyncio

from domain.accounts import USERNAME, Account, Role, check_new_password, hash_password
from domain.ops_ports import AccountStore


async def ensure_bootstrap_admin(
    accounts: AccountStore, username: str | None, password: str | None
) -> bool:
    """Creates the first platform administrator when none exists. It must change the password at
    first sign-in. A no-op once any active platform administrator exists."""
    if not username or not password:
        return False
    if await accounts.count_active_platform_admins() > 0:
        return False
    name = username.strip().lower()
    if not USERNAME.match(name):
        raise SystemExit("RAG_BOOTSTRAP_ADMIN_USER: 3-32 characters, lowercase letters, digits, . - _")
    try:
        check_new_password(password, name)
    except ValueError as exc:
        raise SystemExit(f"RAG_BOOTSTRAP_ADMIN_PASSWORD: {exc}") from exc
    created = await accounts.create(
        Account(
            name, Role.PLATFORM_ADMIN, None, (),
            await asyncio.to_thread(hash_password, password),
            must_change_password=True,
            created_by="bootstrap",
        )  # fmt: skip
    )
    if created:
        print(f"[startup] created the first platform administrator '{name}' (password change required)")
    return created

