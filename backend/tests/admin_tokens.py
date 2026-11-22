import time

import jwt


def admin_token(
    secret: str,
    role: str = "platform_admin",
    tenant: str | None = None,
    group: str | None = None,
    *,
    aud: str = "rag-admin",
    exp_in: int = 300,
    sub: str = "tester",
) -> str:
    now = int(time.time())
    claims: dict[str, object] = {"sub": sub, "role": role, "aud": aud, "iat": now, "exp": now + exp_in}
    if tenant is not None:
        claims["tenant"] = tenant
    if group is not None:
        claims["group"] = group
    return jwt.encode(claims, secret, algorithm="HS256")


def admin_headers(
    secret: str,
    role: str = "platform_admin",
    tenant: str | None = None,
    group: str | None = None,
) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token(secret, role, tenant, group)}"}

