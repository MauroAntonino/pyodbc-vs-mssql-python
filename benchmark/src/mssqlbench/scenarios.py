"""The benchmark scenarios.

Every scenario returns a flat list of result dicts so the report and chart
layers never need to know how a number was produced.
"""

from __future__ import annotations

import random
import statistics
import threading
import time
from datetime import datetime, timezone

from .config import BenchmarkConfig
from .drivers import Driver
from .queries import (
    DELETE_ROW,
    INSERT_ROW,
    POINT_SELECT,
    TRUNCATE_WRITES,
    UPDATE_ROW,
    WRITE_IDS,
    point_select_query,
    result_set_query,
)
from .stats import Measurement, percentile


def _warmup(cursor, iterations: int, table_rows: int) -> None:
    for i in range(iterations):
        cursor.execute(POINT_SELECT, ((i % table_rows) + 1,))
        cursor.fetchone()


def point_select(driver: Driver, config: BenchmarkConfig) -> dict:
    """Scenario 1 - single row by primary key, one connection, no concurrency.

    Isolates per-statement overhead: parameter binding, round trip, and the
    cost of materializing a single ten-column row.
    """
    iterations = config.point_iterations

    conn = driver.connect()
    cursor = conn.cursor()

    try:
        _warmup(cursor, config.warmup_iterations, config.table_rows)

        # Deterministic but non-sequential access, so we are not measuring a
        # purely sequential walk of the clustered index.
        rng = random.Random(1234)
        ids = [rng.randrange(1, config.table_rows + 1) for _ in range(iterations)]

        measurement = Measurement()

        start_total = time.perf_counter()

        for user_id in ids:
            start = time.perf_counter()

            cursor.execute(POINT_SELECT, (user_id,))
            row = cursor.fetchone()

            measurement.latencies_ms.append((time.perf_counter() - start) * 1000)

            if row is not None:
                measurement.rows += 1

        measurement.wall_seconds = time.perf_counter() - start_total
        measurement.operations = iterations
    finally:
        conn.close()

    return {
        "scenario": "point_select",
        "driver": driver.name,
        "label": "SELECT ... WHERE id = ?",
        "batch_size": 1,
        "workers": 1,
        **measurement.summary(),
    }


def result_set(driver: Driver, config: BenchmarkConfig) -> list[dict]:
    """Scenario 2 - transport and materialization of N rows per query.

    The whole result set is drained with fetchall(), so the number reflects how
    fast each driver converts wire data into Python objects.
    """
    results: list[dict] = []

    conn = driver.connect()
    cursor = conn.cursor()

    try:
        _warmup(cursor, config.warmup_iterations, config.table_rows)

        for top in config.result_set_sizes:
            query = result_set_query(top)
            iterations = config.result_set_iterations

            rng = random.Random(top)
            max_start = max(1, config.table_rows - top)
            offsets = [rng.randrange(1, max_start + 1) for _ in range(iterations)]

            # Prime the plan cache for this TOP size.
            cursor.execute(query, (1,))
            cursor.fetchall()

            measurement = Measurement()

            start_total = time.perf_counter()

            for offset in offsets:
                start = time.perf_counter()

                cursor.execute(query, (offset,))
                rows = cursor.fetchall()

                measurement.latencies_ms.append((time.perf_counter() - start) * 1000)
                measurement.rows += len(rows)

            measurement.wall_seconds = time.perf_counter() - start_total
            measurement.operations = iterations

            results.append(
                {
                    "scenario": "result_set",
                    "driver": driver.name,
                    "label": f"TOP {top}",
                    "batch_size": top,
                    "workers": 1,
                    **measurement.summary(),
                }
            )

            print(
                f"  [{driver.name}] TOP {top:>6}: "
                f"{measurement.summary()['qps']:>9.2f} qps  "
                f"{measurement.summary()['rows_per_second']:>12.0f} rows/s"
            )
    finally:
        conn.close()

    return results


def _profile_loop(cursor, query_for, ids) -> tuple[list[float], list[float], float]:
    """Run the point-select loop, timing execute() and fetchone() separately.

    Returns (execute_ms, fetch_ms, wall_seconds). Two extra clock reads per
    iteration are added compared with scenario 1; at ~0.2 ms per query their
    cost is far below the difference being measured, but it does mean the
    totals here are not directly comparable to scenario 1's.
    """
    execute_ms: list[float] = []
    fetch_ms: list[float] = []

    start_total = time.perf_counter()

    for index, user_id in enumerate(ids):
        query = query_for(index)

        t0 = time.perf_counter()
        cursor.execute(query, (user_id,))
        t1 = time.perf_counter()
        cursor.fetchone()
        t2 = time.perf_counter()

        execute_ms.append((t1 - t0) * 1000)
        fetch_ms.append((t2 - t1) * 1000)

    return execute_ms, fetch_ms, time.perf_counter() - start_total


def single_row_profile(driver: Driver, config: BenchmarkConfig) -> list[dict]:
    """Scenario 5 - where the time goes on a single-row select.

    Two questions, both raised in the upstream discussion:

    1. Is the cost in `execute()` or in `fetchone()`? Each is timed on its own.
    2. Does it scale with the number of columns? The same query is run
       projecting 1, 2, 5 and 10 columns. A gap that grows with the column
       count points at per-column conversion or description handling; a gap
       already present with a single INT points at fixed per-call cost.

    A third pass repeats the 10-column case with the SQL text changing on every
    iteration, which checks whether either driver relies on seeing identical
    statement text to reuse a prepared statement.
    """
    results: list[dict] = []

    iterations = config.profile_iterations

    conn = driver.connect()
    cursor = conn.cursor()

    def record(label: str, columns: int, sql_text: str, execute_ms, fetch_ms, wall) -> None:
        total = Measurement(
            latencies_ms=[e + f for e, f in zip(execute_ms, fetch_ms)],
            wall_seconds=wall,
            operations=len(execute_ms),
            rows=len(execute_ms),
        )

        summary = total.summary()

        results.append(
            {
                "scenario": "single_row_profile",
                "driver": driver.name,
                "label": label,
                "columns": columns,
                "sql_text": sql_text,
                "batch_size": 1,
                "workers": 1,
                "execute_avg_ms": statistics.mean(execute_ms),
                "execute_p50_ms": percentile(execute_ms, 50),
                "execute_p95_ms": percentile(execute_ms, 95),
                "fetch_avg_ms": statistics.mean(fetch_ms),
                "fetch_p50_ms": percentile(fetch_ms, 50),
                "fetch_p95_ms": percentile(fetch_ms, 95),
                **summary,
            }
        )

        print(
            f"  [{driver.name}] {label:<28} "
            f"execute {statistics.mean(execute_ms):>7.4f} ms  "
            f"fetch {statistics.mean(fetch_ms):>7.4f} ms  "
            f"total {summary['avg_ms']:>7.4f} ms"
        )

    try:
        _warmup(cursor, config.warmup_iterations, config.table_rows)

        # Same id sequence for every column count and both drivers.
        rng = random.Random(1234)
        ids = [rng.randrange(1, config.table_rows + 1) for _ in range(iterations)]

        for columns in config.profile_column_counts:
            query = point_select_query(columns)

            # Prime the plan cache for this projection.
            cursor.execute(query, (ids[0],))
            cursor.fetchone()

            execute_ms, fetch_ms, wall = _profile_loop(
                cursor, lambda _index: query, ids
            )

            record(f"{columns} col", columns, "fixed", execute_ms, fetch_ms, wall)

        # Statement-text reuse check: same query, different text every call.
        columns = max(config.profile_column_counts)

        execute_ms, fetch_ms, wall = _profile_loop(
            cursor,
            lambda index: point_select_query(columns, variant=index),
            ids,
        )

        record(
            f"{columns} col, rotating SQL text",
            columns,
            "rotating",
            execute_ms,
            fetch_ms,
            wall,
        )
    finally:
        conn.close()

    return results

def _write_row(index: int) -> tuple:
    return (
        f"user_{index}",
        f"user_{index}@example.com",
        "John",
        "Doe",
        20 + (index % 50),
        ("Brazil", "USA", "UK")[index % 3],
        round((index % 10000) * 1.25, 2),
        index % 2,
        datetime.now(timezone.utc).replace(tzinfo=None),
    )


class _Commit:
    """Commit cadence for a write pass.

    In `autocommit` mode the server flushes the log once per statement, which
    caps every driver at the same rate and hides driver overhead entirely. The
    `transaction` mode commits once per batch, so what is left to measure is
    the client-side cost per statement.
    """

    def __init__(self, conn, mode: str, batch_size: int) -> None:
        self.conn = conn
        self.mode = mode
        self.batch_size = batch_size
        self.count = 0

    @property
    def in_transaction(self) -> bool:
        return self.mode == "transaction"

    def tick(self) -> None:
        if not self.in_transaction:
            return

        self.count += 1

        if self.count % self.batch_size == 0:
            self.conn.commit()

    def flush(self) -> None:
        if self.in_transaction:
            self.conn.commit()
            self.count = 0


def _enable_fast_executemany(cursor) -> bool:
    """pyodbc can turn executemany into a real batched insert; opt in when
    available so we compare each driver's best batch path, not its slowest.

    The attribute must already exist: any Python object accepts a new
    attribute silently, so setting one blindly would report a fast path that
    the driver never implemented.
    """
    if not hasattr(cursor, "fast_executemany"):
        return False

    try:
        cursor.fast_executemany = True
    except Exception:
        return False

    return bool(getattr(cursor, "fast_executemany", False))


def _write_pass(driver: Driver, config: BenchmarkConfig, mode: str) -> list[dict]:
    rows = config.write_iterations
    batch_size = config.write_batch_size

    results: list[dict] = []

    conn = driver.connect()

    if mode == "transaction":
        conn.autocommit = False

    cursor = conn.cursor()
    commit = _Commit(conn, mode, batch_size)

    suffix = "autocommit" if mode == "autocommit" else f"tx/{batch_size}"

    def record(operation: str, measurement: Measurement, **extra) -> None:
        summary = measurement.summary()

        results.append(
            {
                "scenario": "write_ops",
                "driver": driver.name,
                "label": f"{operation} [{suffix}]",
                "operation": operation,
                "commit_mode": mode,
                "batch_size": extra.pop("batch_size", 1),
                "workers": 1,
                **extra,
                **summary,
            }
        )

        print(
            f"  [{driver.name}] {operation:<22} {suffix:<12} "
            f"{summary['rows_per_second']:>10.0f} rows/s  "
            f"p95 {summary['p95_ms']:>7.3f} ms"
        )

    def truncate() -> None:
        cursor.execute(TRUNCATE_WRITES)
        commit.flush()

    try:
        truncate()

        # --- INSERT, one row per statement ------------------------------
        measurement = Measurement()
        start_total = time.perf_counter()

        for i in range(rows):
            payload = _write_row(i)

            start = time.perf_counter()
            cursor.execute(INSERT_ROW, payload)
            measurement.latencies_ms.append((time.perf_counter() - start) * 1000)

            commit.tick()

        commit.flush()

        measurement.wall_seconds = time.perf_counter() - start_total
        measurement.operations = rows
        measurement.rows = rows

        record("INSERT row-by-row", measurement)

        # --- INSERT via executemany -------------------------------------
        truncate()

        batches = [
            [_write_row(i) for i in range(offset, min(offset + batch_size, rows))]
            for offset in range(0, rows, batch_size)
        ]

        fast = _enable_fast_executemany(cursor)

        try:
            measurement = Measurement()
            start_total = time.perf_counter()

            for batch in batches:
                start = time.perf_counter()
                cursor.executemany(INSERT_ROW, batch)
                measurement.latencies_ms.append((time.perf_counter() - start) * 1000)
                measurement.rows += len(batch)

                commit.flush()

            measurement.wall_seconds = time.perf_counter() - start_total
            measurement.operations = len(batches)

            record(
                "INSERT executemany",
                measurement,
                batch_size=batch_size,
                fast_executemany=fast,
            )
        except Exception as exc:
            print(f"  [{driver.name}] executemany failed: {exc}")

            # Refill row-by-row so UPDATE/DELETE still have rows, but do not
            # report the fallback as an executemany result.
            truncate()

            for i in range(rows):
                cursor.execute(INSERT_ROW, _write_row(i))
                commit.tick()

            commit.flush()

        # --- UPDATE ------------------------------------------------------
        cursor.execute(WRITE_IDS)
        ids = [row[0] for row in cursor.fetchall()]

        if not ids:
            raise RuntimeError("write table is empty after the insert phase")

        rng = random.Random(4321)
        update_ids = [rng.choice(ids) for _ in range(rows)]

        measurement = Measurement()
        start_total = time.perf_counter()

        for index, row_id in enumerate(update_ids):
            start = time.perf_counter()
            cursor.execute(UPDATE_ROW, (round(index * 0.75, 2), index % 2, row_id))
            measurement.latencies_ms.append((time.perf_counter() - start) * 1000)

            commit.tick()

        commit.flush()

        measurement.wall_seconds = time.perf_counter() - start_total
        measurement.operations = rows
        measurement.rows = rows

        record("UPDATE by id", measurement)

        # --- DELETE ------------------------------------------------------
        measurement = Measurement()
        start_total = time.perf_counter()

        for row_id in ids:
            start = time.perf_counter()
            cursor.execute(DELETE_ROW, (row_id,))
            measurement.latencies_ms.append((time.perf_counter() - start) * 1000)

            commit.tick()

        commit.flush()

        measurement.wall_seconds = time.perf_counter() - start_total
        measurement.operations = len(ids)
        measurement.rows = len(ids)

        record("DELETE by id", measurement)

        truncate()
    finally:
        conn.close()

    return results


def write_ops(driver: Driver, config: BenchmarkConfig) -> list[dict]:
    """Scenario 4 - INSERT / UPDATE / DELETE, single connection.

    Runs against dbo.users_writes, never dbo.users, so the read scenarios keep
    seeing a stable 100k rows. Each phase leaves the table in the state the
    next one needs: insert -> executemany insert -> update -> delete. Every
    phase runs once per commit mode, because the commit cadence - not the
    driver - dominates the autocommit numbers.
    """
    results: list[dict] = []

    for mode in config.write_commit_modes:
        results.extend(_write_pass(driver, config, mode))

    return results


def _concurrency_worker(
    driver: Driver,
    config: BenchmarkConfig,
    barrier: threading.Barrier,
    stop_at: threading.Event,
    seed: int,
    out: list,
    slot: int,
) -> None:
    """One worker: own connection, own cursor, time-boxed point-select loop."""
    latencies: list[float] = []
    operations = 0

    conn = None

    try:
        conn = driver.connect()
        cursor = conn.cursor()

        _warmup(cursor, min(config.warmup_iterations, 20), config.table_rows)

        rng = random.Random(seed)

        # Connections are established before the clock starts, so connection
        # setup does not leak into the measured window.
        barrier.wait(timeout=120)

        started = time.perf_counter()

        while not stop_at.is_set():
            user_id = rng.randrange(1, config.table_rows + 1)

            start = time.perf_counter()

            cursor.execute(POINT_SELECT, (user_id,))
            cursor.fetchone()

            latencies.append((time.perf_counter() - start) * 1000)
            operations += 1

        out[slot] = (latencies, operations, started, time.perf_counter())
    except Exception as exc:  # a single failing worker must not hide the rest
        out[slot] = exc

        try:
            barrier.abort()
        except Exception:
            pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def concurrency(driver: Driver, config: BenchmarkConfig) -> list[dict]:
    """Scenario 3 - QPS as the number of concurrent workers grows.

    Each level runs for a fixed duration rather than a fixed iteration count,
    so every level gets the same amount of wall-clock time under load.
    """
    results: list[dict] = []

    for workers in config.worker_levels:
        # +1 for this thread: the timer starts only once all workers are ready.
        barrier = threading.Barrier(workers + 1)
        stop_at = threading.Event()
        out: list = [None] * workers

        threads = [
            threading.Thread(
                target=_concurrency_worker,
                args=(driver, config, barrier, stop_at, 9000 + i, out, i),
                daemon=True,
                name=f"{driver.name}-w{i}",
            )
            for i in range(workers)
        ]

        for thread in threads:
            thread.start()

        try:
            barrier.wait(timeout=180)
        except threading.BrokenBarrierError:
            pass

        # Every worker is now connected and warm, so the timer starts here.
        deadline = time.perf_counter() + config.concurrency_seconds

        while time.perf_counter() < deadline and any(t.is_alive() for t in threads):
            time.sleep(0.02)

        stop_at.set()

        for thread in threads:
            thread.join(timeout=120)

        failures = [item for item in out if isinstance(item, Exception)]

        if failures:
            print(
                f"  [{driver.name}] {workers:>3} workers: FAILED "
                f"({len(failures)}/{workers}) - {failures[0]}"
            )
            continue

        completed = [item for item in out if item is not None]

        if not completed:
            continue

        measurement = Measurement()

        for latencies, operations, _started, _ended in completed:
            measurement.latencies_ms.extend(latencies)
            measurement.operations += operations

        first_start = min(item[2] for item in completed)
        last_end = max(item[3] for item in completed)

        measurement.wall_seconds = last_end - first_start
        measurement.rows = measurement.operations

        summary = measurement.summary()

        results.append(
            {
                "scenario": "concurrency",
                "driver": driver.name,
                "label": f"{workers} workers",
                "batch_size": 1,
                "workers": workers,
                **summary,
            }
        )

        print(
            f"  [{driver.name}] {workers:>3} workers: "
            f"{summary['qps']:>9.2f} qps  "
            f"p95 {summary['p95_ms']:>7.3f} ms"
        )

    return results
