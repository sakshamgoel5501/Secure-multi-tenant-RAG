from typing import Any

from domain.accounts import Account, Role, hash_password

PASSWORD = "correct horse battery"


def make_account(
    username: str = "alice",
    role: Role = Role.USER,
    tenant: str | None = "t1",
    groups: tuple[str, ...] = ("eng",),
    *,
    password: str = PASSWORD,
    must_change: bool = False,
    **extra: Any,
) -> Account:
    return Account(
        username, role, tenant, groups, hash_password(password),
        must_change_password=must_change, **extra,
    )  # fmt: skip

