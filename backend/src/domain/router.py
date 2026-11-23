from __future__ import annotations

import re
from enum import StrEnum


class Route(StrEnum):
    SIMPLE = "simple"
    MULTI = "multi"


_MARKERS = re.compile(
    r"\b(compare|comparison|versus|vs\.?|difference between|differences between|both|each of|as well as)\b",
    re.IGNORECASE,
)
_AND = re.compile(r"\band\b", re.IGNORECASE)
_LONG = 12  # words: a long sentence with "and" is likely two questions


def classify(query: str) -> Route:
    """Cheap, deterministic, no model call. It decides only whether decomposition is worth
    trying; the decomposer still has the last word, so a false MULTI costs one call, not a
    wrong answer. It errs toward SIMPLE because every MULTI costs latency."""
    q = query.strip()
    if q.count("?") >= 2 or _MARKERS.search(q):
        return Route.MULTI
    if len(q.split()) >= _LONG and _AND.search(q):
        return Route.MULTI
    return Route.SIMPLE

