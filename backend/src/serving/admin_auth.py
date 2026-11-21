from collections.abc import Callable
from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request

ADMIN_AUDIENCE = "rag-admin"  # user tokens use "rag", so neither works as the other


@dataclass(frozen=True, slots=True)
class Principal:
    actor: str
    role: str  # "platform_admin" or "tenant_admin"
    tenant: str | None

    @property
    def platform(self) -> bool:
        return self.role == "platform_admin"

    def can_manage(self, tenant: str) -> bool:
        return self.platform or (self.role == "tenant_admin" and self.tenant == tenant)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def admin_identity(secret: str) -> Callable[[Request], Principal]:
    def identity(request: Request) -> Principal:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise _unauthorized("admin token required")
        try:
            claims = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                audience=ADMIN_AUDIENCE,
                options={"require": ["exp", "sub", "role"]},
            )
        except jwt.InvalidTokenError:
            raise _unauthorized("invalid or expired admin token") from None
        role, tenant = claims.get("role"), claims.get("tenant")
        if role == "platform_admin":
            return Principal(str(claims["sub"]), role, None)
        if role == "tenant_admin" and isinstance(tenant, str) and tenant:
            return Principal(str(claims["sub"]), role, tenant)
        raise _unauthorized("unknown or incomplete admin role")

    return identity


