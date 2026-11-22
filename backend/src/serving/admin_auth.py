from collections.abc import Callable
from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request

ADMIN_AUDIENCE = "rag-admin"  # user tokens use "rag", so neither works as the other


@dataclass(frozen=True, slots=True)
class Principal:
    actor: str
    role: str  # "platform_admin", "tenant_admin" or "group_admin"
    tenant: str | None
    group: str | None = None

    @property
    def platform(self) -> bool:
        return self.role == "platform_admin"

    @property
    def group_scoped(self) -> bool:
        return self.role == "group_admin"

    def can_manage(self, tenant: str) -> bool:
        """Tenant-level reach. Group admins are further limited per document by the routes."""
        return self.platform or (self.role in ("tenant_admin", "group_admin") and self.tenant == tenant)


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
        actor = str(claims["sub"])
        role, tenant, group = claims.get("role"), claims.get("tenant"), claims.get("group")
        if role == "platform_admin":
            return Principal(actor, role, None)
        if role == "tenant_admin" and isinstance(tenant, str) and tenant:
            return Principal(actor, role, tenant)
        if role == "group_admin" and isinstance(tenant, str) and tenant and isinstance(group, str) and group:
            return Principal(actor, role, tenant, group)
        raise _unauthorized("unknown or incomplete admin role")

    return identity

