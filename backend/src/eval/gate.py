from __future__ import annotations

from collections.abc import Mapping

HIGHER_IS_BETTER = (
    "recall_at_5",
    "mrr",
    "ndcg_at_10",
    "answer_correct_rate",
    "refusal_correct_rate",
    "cited_relevant_rate",
)
LOWER_IS_BETTER = ("hallucination_rate",)
MUST_BE_ZERO = ("permission_violations", "revocation_leaks")


def check_gate(
    current: Mapping[str, float], baseline: Mapping[str, float], tolerance: float = 0.02
) -> list[str]:
    """Security metrics have zero tolerance. Quality metrics may wobble by `tolerance` (LLM
    output is not perfectly deterministic) but may not regress beyond it."""
    failures: list[str] = []
    for key in MUST_BE_ZERO:
        if current.get(key, 0.0) != 0.0:
            failures.append(f"{key} = {current[key]:g} (must be 0)")
    for key in HIGHER_IS_BETTER:
        if key in current and key in baseline and current[key] < baseline[key] - tolerance:
            failures.append(f"{key} fell {baseline[key]:.3f} -> {current[key]:.3f}")
    for key in LOWER_IS_BETTER:
        if key in current and key in baseline and current[key] > baseline[key] + tolerance:
            failures.append(f"{key} rose {baseline[key]:.3f} -> {current[key]:.3f}")
    return failures



