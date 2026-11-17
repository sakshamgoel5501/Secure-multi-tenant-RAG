from __future__ import annotations

import math
from collections import Counter, defaultdict, deque
from collections.abc import Mapping, Sequence


def _pct(values: Sequence[float], p: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(p / 100 * len(ordered)) - 1))
    return ordered[index]


class StageStats:
    """Rolling in-memory latency per route and stage. In production this is Prometheus
    histograms; the idea is the same."""

    def __init__(self, window: int = 2000) -> None:
        self._lat: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=window))
        self._status: Counter[str] = Counter()

    def record(
        self, route: str, status: int, total_ms: float, stages: Mapping[str, float]
    ) -> None:
        self._lat[f"{route}:total"].append(total_ms)
        for name, ms in stages.items():
            self._lat[f"{route}:{name}"].append(ms)
        self._status[f"{route}:{status}"] += 1

    def snapshot(self) -> dict[str, object]:
        latency = {
            key: {
                "n": len(vals),
                "p50": round(_pct(vals, 50), 1),
                "p95": round(_pct(vals, 95), 1),
                "max": round(max(vals), 1),
            }
            for key, vals in sorted(self._lat.items())
            if vals
        }
        return {"latency_ms": latency, "status": dict(sorted(self._status.items()))}
    


    