from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from adapters.chaos import COMPONENTS, Faults


class ChaosBody(BaseModel):
    fail: list[str] = Field(default_factory=list)
    delay: dict[str, float] = Field(default_factory=dict)


def mount_chaos(app: FastAPI, faults: Faults) -> None:
    """Adds /chaos. Mounted only when RAG_CHAOS=1: it must never exist in production."""

    @app.post("/chaos")
    async def set_chaos(body: ChaosBody) -> dict[str, Any]:
        unknown = (set(body.fail) | set(body.delay)) - COMPONENTS
        if unknown:
            raise HTTPException(422, f"unknown components: {sorted(unknown)}")
        faults.set(body.fail, body.delay)
        return {"fail": sorted(faults.fail), "delay": faults.delay}

    @app.delete("/chaos")
    async def clear_chaos() -> dict[str, str]:
        faults.clear()
        return {"status": "cleared"}
    
    