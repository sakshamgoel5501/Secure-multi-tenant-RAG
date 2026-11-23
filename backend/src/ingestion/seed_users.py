from __future__ import annotations

import argparse
import asyncio
import os

from adapters.postgres_accounts import PostgresAccountStore
from domain.accounts import Account, Role, check_new_password, hash_password

GROUPS = ("eng", "hr", "fin")


async def seed(password: str, tenants: int, dsn: str) -> None:
    store = PostgresAccountStore(dsn)
    await store.start()
    made: list[str] = []

    async def add(name: str, role: Role, tenant: str | None, groups: tuple[str, ...]) -> None:
        digest = await asyncio.to_thread(hash_password, password)
        account = Account(name, role, tenant, groups, digest, must_change_password=False, created_by="seed")
        if await store.create(account):
            made.append(f"{name:<16} {role.value:<15} {tenant or '-':<9} {','.join(groups)}")

    await add("platform", Role.PLATFORM_ADMIN, None, ())
    for t in range(1, tenants + 1):
        tenant = f"tenant-{t}"
        await add(f"t{t}-admin", Role.TENANT_ADMIN, tenant, ())
        for g in GROUPS:
            await add(f"t{t}-{g}", Role.USER, tenant, (g,))
            await add(f"t{t}-{g}-admin", Role.GROUP_ADMIN, tenant, (g,))
    await store.close()
    print("\n".join(made) or "nothing to create: every account already exists")
    print(f"\n{len(made)} accounts created. They all share the password you passed. Demo use only.")


def main() -> None:
    p = argparse.ArgumentParser(description="Create demo accounts for every tenant and group")
    p.add_argument("--password", default=os.environ.get("RAG_SEED_PASSWORD"))
    p.add_argument("--tenants", type=int, default=3)
    args = p.parse_args()
    if not args.password:
        raise SystemExit("pass --password or set RAG_SEED_PASSWORD")
    try:
        check_new_password(args.password, "")
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    asyncio.run(seed(args.password, args.tenants, os.environ.get("RAG_PG_DSN", "postgresql://localhost/rag")))


if __name__ == "__main__":
    main()

    