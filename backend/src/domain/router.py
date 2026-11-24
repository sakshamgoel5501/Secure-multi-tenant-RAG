from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum


class Route(StrEnum):
    SIMPLE = "simple"
    MULTI = "multi"


_MARKERS = re.compile(
    r"\b(compare|comparison|versus|vs\.?|difference between|differences between|both|each of|as well as)\b",
    re.IGNORECASE,
)
_AND = re.compile(r"\band\b", re.IGNORECASE)
DEFAULT_LONG_WORDS = 12  # a long sentence with "and" is likely two questions


def classify(
    query: str, *, long_words: int = DEFAULT_LONG_WORDS, extra_markers: Sequence[str] = ()
) -> Route:
    """Cheap, deterministic, no model call. It decides only whether decomposition is worth trying;
    the decomposer still has the last word, so a false MULTI costs one call, not a wrong answer."""
    q = query.strip()
    if q.count("?") >= 2 or _MARKERS.search(q):
        return Route.MULTI
    if extra_markers and re.search(
        r"\b(" + "|".join(re.escape(m) for m in extra_markers) + r")\b", q, re.IGNORECASE
    ):
        return Route.MULTI
    if len(q.split()) >= long_words and _AND.search(q):
        return Route.MULTI
    return Route.SIMPLE

