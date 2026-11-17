from __future__ import annotations

import re

_SOURCE = re.compile(r'<source id="(S\d+)">\n(.*?)\n</source>', re.DOTALL)


class ExtractiveLLM:
    """Demo LLM: answers with the first source's text and cites it. No model needed."""

    async def generate(self, system: str, user: str) -> str:
        match = _SOURCE.search(user)
        if match is None:
            return "I don't have enough information to answer."
        return f"{match.group(2)} [{match.group(1)}]"
    



    