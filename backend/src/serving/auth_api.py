from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from domain.accounts import Account, account_json
from serving.auth_service import AdminDisabled, AuthService


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class PasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


def create_auth_router(service: AuthService) -> APIRouter:
    router = APIRouter(prefix="/auth")

    async def current(authorization: str | None) -> Account:
        scheme, _, token = (authorization or "").partition(" ")
        account = await service.resolve(token) if scheme.lower() == "bearer" and token else None
        if account is None:
            raise HTTPException(
                status_code=401, detail="not signed in", headers={"WWW-Authenticate": "Bearer"}
            )
        return account

    @router.post("/login")
    async def login(body: LoginBody) -> dict[str, Any]:
        try:
            result = await service.login(body.username, body.password)
        except AdminDisabled:
            raise HTTPException(status_code=403, detail="administration is disabled on this server") from None
        if result is None:
            raise HTTPException(
                status_code=401,
                detail="incorrect username or password, or the account is temporarily locked",
            )
        account, token = result
        return {"token": token, "expires_in": service.ttl, "account": account_json(account)}

    @router.get("/me")
    async def me(authorization: Annotated[str | None, Header()] = None) -> dict[str, object]:
        return account_json(await current(authorization))

    @router.post("/password")
    async def change_password(
        body: PasswordBody, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        account = await current(authorization)
        try:
            updated = await service.change_password(account, body.current_password, body.new_password)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"token": service.issue(updated), "expires_in": service.ttl, "account": account_json(updated)}

    return router

