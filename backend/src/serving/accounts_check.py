from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException

from domain.accounts import Account
from domain.ops_ports import AccountStore


async def live_account(accounts: AccountStore, claims: Mapping[str, Any]) -> Account:
    """Checks the token's account against the authoritative store on every request, so a disabled
    account, a password reset or a role change takes effect immediately."""
    account = await accounts.get(str(claims["sub"]))
    if account is None or account.disabled or claims.get("tv") != account.token_version:
        raise HTTPException(
            status_code=401, detail="session is no longer valid", headers={"WWW-Authenticate": "Bearer"}
        )
    if account.must_change_password:
        raise HTTPException(status_code=403, detail="password change required")
    return account

