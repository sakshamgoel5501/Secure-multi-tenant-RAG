from __future__ import annotations

import json
import re

from domain.ports import LLM

SYSTEM = (
    "You split questions for a document search system.\n"
    "If the user's question asks about more than one distinct thing, reply with a JSON array of "
    "at most {n} self-contained sub-questions, each answerable on its own.\n"
    "If it is a single question, reply with a JSON array containing only the original question.\n"
    "Reply with the JSON array and nothing else."
)
_ARRAY = re.compile(r"\[.*\]", re.DOTALL)


def parse_parts(raw: str, max_parts: int, max_chars: int = 300) -> list[str]:
    match = _ARRAY.search(raw)
    if match is None:
        return []
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    parts: list[str] = []
    for item in data:
        if isinstance(item, str):
            text = item.strip()
            if text and len(text) <= max_chars and text not in parts:
                parts.append(text)
    return parts[:max_parts]


class LLMDecomposer:
    """Asks the model to split a question. It receives only the user's own text, never documents,
    and its output is only used as search queries inside the normal authorization path."""

    def __init__(self, llm: LLM, max_parts: int = 3) -> None:
        self._llm = llm
        self._max = max_parts

    async def decompose(self, query: str) -> list[str]:
        raw = await self._llm.generate(SYSTEM.format(n=self._max), f"Question: {query}")
        return parse_parts(raw, self._max)
    