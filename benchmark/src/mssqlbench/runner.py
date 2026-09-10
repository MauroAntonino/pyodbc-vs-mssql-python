"""Orchestration: wait for the database, run the selected scenarios, report."""

from __future__ import annotations

import time
from dataclasses import replace

from . import charts, report, scenarios
from .config import BenchmarkConfig
from .drivers import Driver, build_drivers
from .stats import median_of_runs

SCENARIOS = (
    "point_select",
    "result_set",
    "concurrency",
    "write_ops",
    "single_row_profile",
)


def wait_for_database(driver: Driver, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            conn = driver.connect()

            try:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM dbo.users")
                (count,) = cursor.fetchone()
            finally:
                conn.close()

            print(f"Connected via {driver.name}: dbo.users has {count:,} rows.")
            return
        except Exception as exc:
            last_error = exc
            time.sleep(2)

    raise SystemExit(f"Database not reachable after {timeout:.0f}s: {last_error}")


def resolve_table_rows(driver: Driver, config: BenchmarkConfig) -> BenchmarkConfig:
    """Trust the table over the configured row count."""
    conn = driver.connect()

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), MAX(id) FROM dbo.users")
        count, max_id = cursor.fetchone()
    finally:
        conn.close()

    if not count:
        raise SystemExit("dbo.users is empty - run sql/init.sql and sql/seed.sql first.")

    # Point lookups draw ids from 1..table_rows, so cap by MAX(id) to keep
    # every lookup a hit rather than a silent miss.
    return replace(config, table_rows=min(int(count), int(max_id)))


def describe_server(driver: Driver) -> dict:
    """Record what the numbers were measured against, for the JSON metadata."""
    conn = driver.connect()

    try:
        cursor = conn.cursor()

        cursor.execute("SELECT @@VERSION")
        (version,) = cursor.fetchone()

        cursor.execute("SELECT cpu_count, physical_memory_kb FROM sys.dm_os_sys_info")
        cpu_count, memory_kb = cursor.fetchone()
    finally:
        conn.close()

    return {
        "sql_server_version": " ".join(str(version).split())[:160],
        "sql_server_cpu_count": int(cpu_count),
        "sql_server_memory_gb": round(int(memory_kb) / 1024 / 1024, 1),
    }


def run_once(
    drivers: list[Driver], config: BenchmarkConfig, selected: list[str]
) -> list[dict]:
    results: list[dict] = []

    if "point_select" in selected:
        print("\n>>> Scenario 1: point select")

        for driver in drivers:
            result = scenarios.point_select(driver, config)
            results.append(result)

            print(
                f"  [{driver.name}] {result['qps']:>9.2f} qps  "
                f"p95 {result['p95_ms']:>7.3f} ms"
            )

    if "result_set" in selected:
        print("\n>>> Scenario 2: result set")

        for driver in drivers:
            results.extend(scenarios.result_set(driver, config))

    if "concurrency" in selected:
        print("\n>>> Scenario 3: concurrency")

        for driver in drivers:
            results.extend(scenarios.concurrency(driver, config))

    if "write_ops" in selected:
        print("\n>>> Scenario 4: INSERT / UPDATE / DELETE")

        for driver in drivers:
            results.extend(scenarios.write_ops(driver, config))

    if "single_row_profile" in selected:
        print("\n>>> Scenario 5: single row - execute vs fetch, by column count")

        for driver in drivers:
            results.extend(scenarios.single_row_profile(driver, config))

    return results


def run(
    config: BenchmarkConfig,
    driver_names: list[str],
    selected: list[str],
    repeats: int = 1,
) -> list[dict]:
    drivers = build_drivers(config.database, driver_names)

    wait_for_database(drivers[0])
    config = resolve_table_rows(drivers[0], config)
    environment = describe_server(drivers[0])

    print(f"Using {config.table_rows:,} rows for lookups.")
    print(f"Server: {environment['sql_server_version'][:80]}")

    raw_runs: list[list[dict]] = []

    for attempt in range(1, repeats + 1):
        if repeats > 1:
            print(f"\n########## repeat {attempt}/{repeats} ##########")

        raw_runs.append(run_once(drivers, config, selected))

    results = median_of_runs(raw_runs)

    if repeats > 1:
        print(f"\nReporting the median of {repeats} repeats.")

    report.print_tables(results)
    report.print_profile(results)
    report.print_speedup(results, baseline=drivers[0].name)

    json_path = report.write_json(
        results,
        config,
        config.output_dir / "results.json",
        environment=environment,
        raw_runs=raw_runs,
    )
    csv_path = report.write_csv(results, config.output_dir / "results.csv")

    print()
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")

    for path in charts.render_all(results, config.output_dir):
        print(f"PNG:  {path}")

    return results
