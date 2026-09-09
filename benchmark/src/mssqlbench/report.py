"""Console tables plus JSON/CSV export."""

from __future__ import annotations

import csv
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

COLUMNS = [
    ("driver", "Driver", 14, "s"),
    ("label", "Case", 34, "s"),
    ("operations", "Ops", 9, "d"),
    ("qps", "QPS", 12, ".2f"),
    ("rows_per_second", "Rows/s", 14, ".0f"),
    ("avg_ms", "Avg ms", 11, ".4f"),
    ("p50_ms", "p50", 11, ".4f"),
    ("p95_ms", "p95", 11, ".4f"),
    ("p99_ms", "p99", 11, ".4f"),
]

SCENARIO_TITLES = {
    "point_select": "SCENARIO 1 - Point select (single row by primary key)",
    "result_set": "SCENARIO 2 - Result set (transport + materialization)",
    "concurrency": "SCENARIO 3 - Concurrency (point select, N workers)",
    "write_ops": "SCENARIO 4 - Writes (INSERT / UPDATE / DELETE)",
}


def _row_text(result: dict) -> str:
    parts = []

    for key, _header, width, fmt in COLUMNS:
        value = result.get(key)

        if value is None:
            parts.append(f"{'-':>{width}}")
        elif fmt == "s":
            parts.append(f"{str(value):<{width}}")
        elif fmt == "d":
            # A median across repeats can be fractional (e.g. 5 and 6 -> 5.5).
            parts.append(f"{round(value):>{width}d}")
        else:
            parts.append(f"{value:>{width}{fmt}}")

    return "".join(parts)


def _header_text() -> str:
    parts = []

    for _key, header, width, fmt in COLUMNS:
        if fmt == "s":
            parts.append(f"{header:<{width}}")
        else:
            parts.append(f"{header:>{width}}")

    return "".join(parts)


def print_tables(results: list[dict]) -> None:
    total_width = sum(width for _k, _h, width, _f in COLUMNS)

    for scenario, title in SCENARIO_TITLES.items():
        rows = [r for r in results if r["scenario"] == scenario]

        if not rows:
            continue

        print()
        print("=" * total_width)
        print(title)
        print("=" * total_width)
        print(_header_text())
        print("-" * total_width)

        # Group by case so the two drivers sit next to each other.
        for label in dict.fromkeys(r["label"] for r in rows):
            for row in [r for r in rows if r["label"] == label]:
                print(_row_text(row))

        print("=" * total_width)


def print_speedup(results: list[dict], baseline: str = "pyodbc") -> None:
    drivers = list(dict.fromkeys(r["driver"] for r in results))

    others = [d for d in drivers if d != baseline]

    if baseline not in drivers or not others:
        return

    print()
    print(f"RELATIVE QPS (baseline = {baseline}, >1.00x is faster)")
    print("-" * 72)

    for scenario in SCENARIO_TITLES:
        rows = [r for r in results if r["scenario"] == scenario]

        if not rows:
            continue

        for label in dict.fromkeys(r["label"] for r in rows):
            base = next(
                (
                    r
                    for r in rows
                    if r["label"] == label and r["driver"] == baseline
                ),
                None,
            )

            if base is None or not base["qps"]:
                continue

            for driver in others:
                candidate = next(
                    (
                        r
                        for r in rows
                        if r["label"] == label and r["driver"] == driver
                    ),
                    None,
                )

                if candidate is None:
                    continue

                ratio = candidate["qps"] / base["qps"]

                print(
                    f"{scenario:<14}{label:<34}{driver:<16}{ratio:>8.2f}x"
                )

    print("-" * 72)


def _driver_versions() -> dict:
    versions: dict[str, str] = {}

    try:
        import pyodbc

        versions["pyodbc"] = pyodbc.version
        versions["odbc_drivers"] = ", ".join(pyodbc.drivers())
    except Exception:
        pass

    try:
        import mssql_python

        versions["mssql_python"] = getattr(mssql_python, "__version__", "unknown")
    except Exception:
        pass

    return versions


def _hardware() -> dict:
    info: dict = {
        "cpu_count": os.cpu_count(),
        "machine": platform.machine(),
    }

    # Container-visible values: what the benchmark process actually had, which
    # is what a reader needs in order to compare against their own run.
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    info["memory_gb"] = round(int(line.split()[1]) / 1024 / 1024, 1)
                    break
    except OSError:
        pass

    return info


def _metadata(config, environment: dict | None = None) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "drivers": _driver_versions(),
        "hardware": _hardware(),
        "environment": environment or {},
        "table_rows": config.table_rows,
        "point_iterations": config.point_iterations,
        "result_set_sizes": config.result_set_sizes,
        "result_set_iterations": config.result_set_iterations,
        "write_iterations": config.write_iterations,
        "write_batch_size": config.write_batch_size,
        "write_commit_modes": config.write_commit_modes,
        "worker_levels": config.worker_levels,
        "concurrency_seconds": config.concurrency_seconds,
    }


def write_json(
    results: list[dict],
    config,
    path: Path,
    *,
    environment: dict | None = None,
    raw_runs: list[list[dict]] | None = None,
) -> Path:
    payload = {
        "metadata": _metadata(config, environment),
        "results": results,
    }

    # With --repeat, `results` holds the medians; the individual repeats stay
    # in the same file so the spread is auditable.
    if raw_runs and len(raw_runs) > 1:
        payload["repeats"] = raw_runs

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return path


def write_csv(results: list[dict], path: Path) -> Path:
    if not results:
        return path

    # Scenarios contribute different extra keys (fast_executemany, commit_mode
    # ...), so the header is the union, in first-seen order.
    fieldnames: list[str] = []

    for result in results:
        for key in result:
            if key not in fieldnames:
                fieldnames.append(key)

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    return path
