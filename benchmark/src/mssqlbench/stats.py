"""Latency statistics shared by every scenario."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Sequence


def percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolation percentile. `values` need not be sorted."""
    if not values:
        return float("nan")

    ordered = sorted(values)

    index = (len(ordered) - 1) * p / 100

    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)

    weight = index - lower

    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def median_of_runs(runs: Sequence[Sequence[dict]]) -> list[dict]:
    """Collapse N repeats into one result set, taking the median per metric.

    Results are matched on (scenario, driver, label). Median rather than mean:
    a single slow repeat (a background process, a checkpoint) should not move
    the reported number.
    """
    if not runs:
        return []

    if len(runs) == 1:
        return list(runs[0])

    grouped: dict[tuple, list[dict]] = {}
    order: list[tuple] = []

    for run in runs:
        for result in run:
            key = (result["scenario"], result["driver"], result["label"])

            if key not in grouped:
                grouped[key] = []
                order.append(key)

            grouped[key].append(result)

    merged: list[dict] = []

    for key in order:
        entries = grouped[key]
        combined = dict(entries[0])

        for field_name, value in entries[0].items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue

            values = [
                entry[field_name]
                for entry in entries
                if isinstance(entry.get(field_name), (int, float))
                and not isinstance(entry.get(field_name), bool)
            ]

            if values:
                combined[field_name] = statistics.median(values)

        combined["repeats"] = len(entries)

        merged.append(combined)

    return merged


@dataclass
class Measurement:
    """One measured run: latencies in ms plus the wall-clock span."""

    latencies_ms: list[float] = field(default_factory=list)
    wall_seconds: float = 0.0
    operations: int = 0
    rows: int = 0

    def summary(self) -> dict:
        latencies = self.latencies_ms

        ops = self.operations or len(latencies)
        wall = self.wall_seconds or float("nan")

        return {
            "operations": ops,
            "rows": self.rows,
            "wall_seconds": wall,
            "qps": ops / wall if wall else float("nan"),
            "rows_per_second": self.rows / wall if wall else float("nan"),
            "avg_ms": statistics.mean(latencies) if latencies else float("nan"),
            "min_ms": min(latencies) if latencies else float("nan"),
            "p50_ms": percentile(latencies, 50),
            "p95_ms": percentile(latencies, 95),
            "p99_ms": percentile(latencies, 99),
            "max_ms": max(latencies) if latencies else float("nan"),
        }
