from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from ingestion.corpus import GoldenQuery

_MARKER = re.compile(r"\[S\d+\]")
_NUMBER = re.compile(r"\d+")


@dataclass(frozen=True, slots=True)
class AskResult:
    answer: str
    grounded: bool
    degraded: tuple[str, ...]
    cited: tuple[tuple[str, int, int], ...]  # (document_id, start_offset, end_offset)


@dataclass(frozen=True, slots=True)
class AnswerScore:
    answerable: bool
    correct: bool  # answerable: has the expected fact AND is grounded. Unanswerable: refused.
    cited_relevant: bool  # answerable only: cited the document that holds the answer
    hallucinated: bool  # the answer contains a number found neither in its citations nor the question


def score_answer(golden: GoldenQuery, result: AskResult, texts: Mapping[str, str]) -> AnswerScore:
    """`texts` is the ground-truth corpus (document_id -> text), independent of the system under test."""
    answer = _MARKER.sub("", result.answer)
    cited_text = " ".join(texts.get(doc, "")[s:e] for doc, s, e in result.cited)
    supported = set(_NUMBER.findall(cited_text)) | set(_NUMBER.findall(golden.question))
    hallucinated = bool(set(_NUMBER.findall(answer)) - supported)

    if golden.answerable:
        pattern = rf"(?<![\w-]){re.escape(golden.expected)}(?![\w-])"
        found = re.search(pattern, answer, re.IGNORECASE) is not None
        correct = found and result.grounded
        cited_relevant = any(doc == golden.relevant_doc_id for doc, _, _ in result.cited)
    else:
        correct = not result.grounded
        cited_relevant = False
    return AnswerScore(golden.answerable, correct, cited_relevant, hallucinated)



