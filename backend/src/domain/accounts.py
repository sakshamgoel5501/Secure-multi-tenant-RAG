from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import os
import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    USER = "user"
    GROUP_ADMIN = "group_admin"
    TENANT_ADMIN = "tenant_admin"
    PLATFORM_ADMIN = "platform_admin"


ADMIN_ROLES = frozenset({Role.GROUP_ADMIN, Role.TENANT_ADMIN, Role.PLATFORM_ADMIN})
USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
NAME = re.compile(r"^[\w-]{1,32}$")  # tenant and group ids
MIN_PASSWORD = 12
MAX_PASSWORD = 128

_N, _R, _P = 2**14, 8, 1  # scrypt cost: about 16 MiB and tens of milliseconds
_MAXMEM = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Account:
    username: str
    role: Role
    tenant: str | None
    groups: tuple[str, ...]
    password_hash: str
    disabled: bool = False
    must_change_password: bool = True
    token_version: int = 0  # bumped on password change or reset, which ends every older session
    failed_attempts: int = 0
    locked_until: float = 0.0  # epoch seconds
    created_by: str = ""
    created_at: str = ""
    last_login: str = ""


def account_json(a: Account) -> dict[str, object]:
    """Everything a client may see. Never the hash."""
    return {
        "username": a.username,
        "role": a.role.value,
        "tenant": a.tenant,
        "groups": list(a.groups),
        "disabled": a.disabled,
        "must_change_password": a.must_change_password,
        "last_login": a.last_login,
        "created_by": a.created_by,
    }


def validate_membership(role: Role, tenant: str | None, groups: Sequence[str]) -> None:
    for name in ([tenant] if tenant else []) + list(groups):
        if not NAME.match(name):
            raise ValueError(f"invalid name: {name!r}")
    if role is Role.PLATFORM_ADMIN:
        if tenant or groups:
            raise ValueError("platform administrators have no tenant or groups")
        return
    if not tenant:
        raise ValueError("a tenant is required for this role")
    if role is Role.USER and not groups:
        raise ValueError("a user needs at least one group")
    if role is Role.GROUP_ADMIN and len(groups) != 1:
        raise ValueError("a group administrator has exactly one group")
    if role is Role.TENANT_ADMIN and groups:
        raise ValueError("tenant administrators have no groups")


def check_new_password(password: str, username: str) -> None:
    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        raise ValueError(f"passwords need {MIN_PASSWORD} to {MAX_PASSWORD} characters")
    if username and username.lower() in password.lower():
        raise ValueError("the password must not contain the username")


def generate_password() -> str:
    return secrets.token_urlsafe(12)  # 16 characters


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=_MAXMEM, dklen=32
    )
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        candidate = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt),
            n=int(n), r=int(r), p=int(p),
            maxmem=_MAXMEM,
            dklen=len(expected),
        )  # fmt: skip
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


@functools.cache
def dummy_hash() -> str:
    """Verified against when a username doesn't exist, so timing doesn't reveal which names do."""
    return hash_password(secrets.token_urlsafe(16))

