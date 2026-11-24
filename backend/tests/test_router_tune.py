from eval.router_tune import evaluate

ROWS = [("a b c d e f g h i j k l and m", True), ("short question", False)]


def test_threshold_changes_recall() -> None:
    assert evaluate(ROWS, 12) == (1.0, 1.0, 1.0)
    precision, recall, _ = evaluate(ROWS, 30)
    assert recall == 0.0 and precision == 0.0

    