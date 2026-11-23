import pytest

from domain.router import Route, classify


@pytest.mark.parametrize(
    "query",
    [
        "What is the team size for project amber-falcon-0?",
        "Which project is tracked by ticket TKT-1001?",
        "leave policy",
        "What is the team size and budget for project X?",  # short: "and" alone is not enough
    ],
)
def test_single_questions_stay_simple(query: str) -> None:
    assert classify(query) is Route.SIMPLE


@pytest.mark.parametrize(
    "query",
    [
        "Compare the leave policy with the travel policy",
        "leave policy versus travel policy",
        "What is the notice period? Who approves it?",
        "What is the team size for project amber-falcon-0 and the annual budget for project cobalt-falcon-2?",
        "What is the difference between the two retention periods",
    ],
)
def test_multi_part_questions_are_routed(query: str) -> None:
    assert classify(query) is Route.MULTI
    