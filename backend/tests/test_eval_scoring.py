from domain.models import DocumentId, GroupId, TenantId
from eval.scoring import AskResult, score_answer
from ingestion.corpus import GoldenQuery

TEXT = "Project amber-falcon-0 is owned by the mobile team. The team size for project amber-falcon-0 is 61 people. Tracking ticket: TKT-1000."
TEXTS = {"d1": TEXT}


def golden(expected: str, answerable: bool = True) -> GoldenQuery:
    return GoldenQuery(
        TenantId("t"), GroupId("g"), "What is the team size for project amber-falcon-0?",
        DocumentId("d1"), answerable, expected,
    )


def result(answer: str, grounded: bool = True) -> AskResult:
    return AskResult(answer, grounded, (), (("d1", 0, len(TEXT)),) if grounded else ())


def test_correct_grounded_answer() -> None:
    s = score_answer(golden("61"), result("The team size is 61 people [S1]."), TEXTS)
    assert s.correct and s.cited_relevant and not s.hallucinated


def test_wrong_number_is_incorrect_and_flagged_as_hallucination() -> None:
    s = score_answer(golden("61"), result("The team size is 62 people [S1]."), TEXTS)
    assert not s.correct and s.hallucinated


def test_expected_token_must_match_whole_number() -> None:
    s = score_answer(golden("6"), result("The team size is 61 people [S1]."), TEXTS)
    assert not s.correct


def test_ticket_style_answer_matches_code() -> None:
    g = golden("amber-falcon-0")
    s = score_answer(g, result("It is project amber-falcon-0 [S1]."), TEXTS)
    assert s.correct and not s.hallucinated


def test_unanswerable_question_answered_is_a_failure() -> None:
    s = score_answer(golden("", answerable=False), result("The budget is 61 [S1]."), TEXTS)
    assert not s.correct


def test_unanswerable_question_refused_is_correct() -> None:
    refusal = AskResult("I don't have enough information.", False, (), ())
    assert score_answer(golden("", answerable=False), refusal, TEXTS).correct


    