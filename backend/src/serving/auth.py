from collections.abc import Awaitable, Callable

import jwt
from fastapi import HTTPException, Request

from domain.models import GroupId, SecurityContext, TenantId, UserId
from domain.ports import EpochSource


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def jwt_identity(
    secret: str, epochs: EpochSource, *, audience: str = "rag"
) -> Callable[[Request], Awaitable[SecurityContext]]:
    """Builds the identity dependency.

    The token proves WHO the caller is (tenant, user, groups). The policy epoch is NOT taken from
    the token or the client: it is read from the authorization store at request start. Every
    revocation committed before this request began is therefore visible to it.
    Caveat: groups come from the token, so a group-membership change takes effect when the token
    expires. Production keeps TTLs short or resolves groups server-side.
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
        groups = claims.get("groups", [])
        if not isinstance(groups, list):
            raise _unauthorized("malformed groups claim")
        epoch = await epochs.current_epoch()  # AuthzUnavailable -> 503, fail closed
        return SecurityContext(
            tenant_id=TenantId(str(claims["tenant"])),
            user_id=UserId(str(claims["sub"])),
            group_ids=frozenset(GroupId(str(g)) for g in groups),
            policy_epoch=epoch,
        )

    return identity



