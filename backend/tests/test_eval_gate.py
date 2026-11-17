from eval.gate import check_gate

BASE = {"recall_at_5": 0.95, "mrr": 0.90, "hallucination_rate": 0.0}


def test_identical_metrics_pass() -> None:
    assert check_gate(dict(BASE), BASE) == []


def test_quality_regression_beyond_tolerance_fails() -> None:
    cur = {"recall_at_5": 0.80, "mrr": 0.90, "hallucination_rate": 0.10}
    failures = check_gate(cur, BASE)
    assert any("recall_at_5" in f for f in failures)
    assert any("hallucination_rate" in f for f in failures)


def test_small_dip_within_tolerance_passes() -> None:
    assert check_gate({"recall_at_5": 0.94, "mrr": 0.89}, BASE, tolerance=0.02) == []


def test_security_metrics_have_zero_tolerance_even_if_quality_improves() -> None:
    cur = {"recall_at_5": 1.0, "mrr": 1.0, "permission_violations": 1.0}
    assert any("permission_violations" in f for f in check_gate(cur, BASE))


    