from __future__ import annotations

import argparse
import json
from pathlib import Path

from domain.router import Route, classify


def evaluate(rows: list[tuple[str, bool]], long_words: int) -> tuple[float, float, float]:
    tp = fp = fn = 0
    for question, multi in rows:
        predicted = classify(question, long_words=long_words) is Route.MULTI
        tp += predicted and multi
        fp += predicted and not multi
        fn += (not predicted) and multi
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def main() -> None:
    p = argparse.ArgumentParser(description="Sweep the router's word threshold over labelled questions")
    p.add_argument("--labels", type=Path, default=Path("data/router_labels.json"))
    args = p.parse_args()
    rows = [(str(r["question"]), bool(r["multi"])) for r in json.loads(args.labels.read_text())]
    print(f"{len(rows)} questions, {sum(m for _, m in rows)} multi-part\n")
    print(f"{'long_words':>10} {'precision':>10} {'recall':>8} {'f1':>6}")
    best = (0.0, 0)
    for n in range(6, 25, 2):
        precision, recall, f1 = evaluate(rows, n)
        print(f"{n:>10} {precision:>10.2f} {recall:>8.2f} {f1:>6.2f}")
        best = max(best, (f1, n))
    print(f"\nbest F1 {best[0]:.2f} at RAG_ROUTER_LONG_WORDS={best[1]}")


if __name__ == "__main__":
    main()

    