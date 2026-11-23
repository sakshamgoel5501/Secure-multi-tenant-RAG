from collections.abc import Awaitable, Callable

import jwt
from fastapi import HTTPException, Request

from domain.accounts import Role
from domain.models import GroupId, SecurityContext, TenantId, UserId
from domain.ops_ports import AccountStore
from domain.ports import EpochSource
from serving.accounts_check import live_account


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def jwt_identity(
    secret: str,
    epochs: EpochSource,
    *,
    audience: str = "rag",
    accounts: AccountStore | None = None,
) -> Callable[[Request], Awaitable[SecurityContext]]:
    """Builds the identity dependency for ordinary users.

    The token proves who the caller is. The policy epoch is read from the authorization store at
    request start, never from the client. With `accounts`, tenant and groups also come from the
    live account and not from the token, so membership changes and disabled accounts apply at once.
    """

    async def identity(request: Request) -> SecurityContext:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise _unauthorized("missing bearer token")
        try:
            claims = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],  # pinned: never trust the algorithm named in the token
                audience=audience,
                options={"require": ["exp", "sub", "tenant"]},
            )
        except jwt.InvalidTokenError:
            raise _unauthorized("invalid or expired token") from None

        if accounts is not None:
            account = await live_account(accounts, claims)
            if account.role is not Role.USER or account.tenant is None:
                raise HTTPException(status_code=403, detail="administrators manage documents, they don't read them")
            tenant, groups = account.tenant, list(account.groups)
        else:
            tenant, groups = str(claims["tenant"]), claims.get("groups", [])
            if not isinstance(groups, list):
                raise _unauthorized("malformed groups claim")

        epoch = await epochs.current_epoch()  # AuthzUnavailable -> 503, fail closed
        return SecurityContext(
            tenant_id=TenantId(tenant),
            user_id=UserId(str(claims["sub"])),
            group_ids=frozenset(GroupId(str(g)) for g in groups),
            policy_epoch=epoch,
        )

    return identity

