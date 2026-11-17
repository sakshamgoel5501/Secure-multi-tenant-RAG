import pytest

from eval.metrics import dedupe, ndcg_at_k, percentile, recall_at_k, reciprocal_rank


def test_recall_at_k() -> None:
    ranked = ["a", "b", "c"]
    assert recall_at_k(ranked, {"c"}, 2) == 0.0
    assert recall_at_k(ranked, {"c"}, 3) == 1.0
    assert recall_at_k(ranked, {"a", "z"}, 3) == 0.5


def test_reciprocal_rank() -> None:
    assert reciprocal_rank(["a", "b", "c"], {"c"}) == pytest.approx(1 / 3)
    assert reciprocal_rank(["a"], {"z"}) == 0.0


def test_ndcg_rewards_earlier_rank() -> None:
    assert ndcg_at_k(["c", "b", "a"], {"c"}, 3) == pytest.approx(1.0)
    assert ndcg_at_k(["a", "b", "c"], {"c"}, 3) == pytest.approx(0.5)  # 1/log2(4)


def test_dedupe_keeps_first_occurrence_and_percentile_is_nearest_rank() -> None:
    assert dedupe(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]
    assert percentile([10.0, 20.0, 30.0, 40.0], 50) == 20.0
    assert percentile([10.0, 20.0, 30.0, 40.0], 95) == 40.0
    assert percentile([], 95) == 0.0


    