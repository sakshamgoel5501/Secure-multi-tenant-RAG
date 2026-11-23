from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

_SOURCE = re.compile(r'<source id="(S\d+)">\n(.*?)\n</source>', re.DOTALL)


class ExtractiveLLM:
    """Demo LLM: answers with the first source's text and cites it. No model needed."""

    def __init__(self, delay: float = 0.03) -> None:
        self._delay = delay  # per word when streaming, so the demo visibly streams

    async def generate(self, system: str, user: str) -> str:
        match = _SOURCE.search(user)
        if match is None:
            return "I don't have enough information to answer."
        return f"{match.group(2)} [{match.group(1)}]"

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        for i, word in enumerate((await self.generate(system, user)).split(" ")):
            if self._delay:
                await asyncio.sleep(self._delay)
            yield word if i == 0 else f" {word}"

            