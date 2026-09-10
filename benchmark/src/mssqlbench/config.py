"""Runtime configuration, resolved from environment variables and CLI flags."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)

    if raw is None or raw.strip() == "":
        return default

    return int(raw)


def _int_list_env(name: str, default: list[int]) -> list[int]:
    raw = os.getenv(name)

    if raw is None or raw.strip() == "":
        return list(default)

    return [int(part) for part in raw.replace(" ", "").split(",") if part]


@dataclass(frozen=True)
class DatabaseConfig:
    host: str = os.getenv("DB_HOST", "sqlserver")
    port: str = os.getenv("DB_PORT", "1433")
    database: str = os.getenv("DB_NAME", "benchmark")
    user: str = os.getenv("DB_USER", "sa")
    password: str = os.getenv("DB_PASSWORD", "YourStrong!Passw0rd")
    encrypt: str = os.getenv("DB_ENCRYPT", "no")
    trust_server_certificate: str = os.getenv("DB_TRUST_CERT", "yes")


@dataclass(frozen=True)
class BenchmarkConfig:
    database: DatabaseConfig = field(default_factory=DatabaseConfig)

    # Total rows available in dbo.users. Used to spread point lookups.
    table_rows: int = _int_env("BENCH_TABLE_ROWS", 100_000)

    # Scenario 1 - point select.
    point_iterations: int = _int_env("BENCH_POINT_ITERATIONS", 10_000)

    # Scenario 2 - result set transport/materialization.
    result_set_sizes: list[int] = field(
        default_factory=lambda: _int_list_env(
            "BENCH_RESULT_SET_SIZES", [100, 1_000, 10_000]
        )
    )
    result_set_iterations: int = _int_env("BENCH_RESULT_SET_ITERATIONS", 200)

    # Scenario 4 - INSERT / UPDATE / DELETE.
    write_iterations: int = _int_env("BENCH_WRITE_ITERATIONS", 5_000)
    write_batch_size: int = _int_env("BENCH_WRITE_BATCH_SIZE", 1_000)
    write_commit_modes: list[str] = field(
        default_factory=lambda: [
            mode
            for mode in os.getenv(
                "BENCH_WRITE_COMMIT_MODES", "autocommit,transaction"
            )
            .replace(" ", "")
            .split(",")
            if mode
        ]
    )

    # Scenario 5 - single-row profiling: execute vs fetch, by column count.
    profile_iterations: int = _int_env("BENCH_PROFILE_ITERATIONS", 10_000)
    profile_column_counts: list[int] = field(
        default_factory=lambda: _int_list_env(
            "BENCH_PROFILE_COLUMNS", [1, 2, 5, 10]
        )
    )

    # Scenario 3 - concurrency.
    worker_levels: list[int] = field(
        default_factory=lambda: _int_list_env(
            "BENCH_WORKER_LEVELS", [1, 5, 10, 25, 50, 100]
        )
    )
    concurrency_seconds: float = float(os.getenv("BENCH_CONCURRENCY_SECONDS", "5"))

    warmup_iterations: int = _int_env("BENCH_WARMUP", 100)
    output_dir: Path = field(
        default_factory=lambda: Path(os.getenv("BENCH_OUTPUT_DIR", "/results"))
    )
