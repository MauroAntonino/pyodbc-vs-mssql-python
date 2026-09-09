"""CLI entrypoint: python -m mssqlbench [options]"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from .config import BenchmarkConfig
from .drivers import ALL_DRIVER_NAMES
from .runner import SCENARIOS, run


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mssqlbench",
        description="Benchmark pyodbc vs mssql-python against SQL Server.",
    )

    parser.add_argument(
        "--drivers",
        default=",".join(ALL_DRIVER_NAMES),
        help=f"comma-separated subset of: {', '.join(ALL_DRIVER_NAMES)}",
    )
    parser.add_argument(
        "--scenarios",
        default=",".join(SCENARIOS),
        help=f"comma-separated subset of: {', '.join(SCENARIOS)}",
    )
    parser.add_argument("--point-iterations", type=int, default=None)
    parser.add_argument("--write-iterations", type=int, default=None)
    parser.add_argument(
        "--write-batch-size",
        type=int,
        default=None,
        help="rows per executemany batch in the write scenario",
    )
    parser.add_argument(
        "--write-commit-modes",
        default=None,
        help="comma-separated: autocommit, transaction",
    )
    parser.add_argument("--result-set-iterations", type=int, default=None)
    parser.add_argument(
        "--result-set-sizes",
        default=None,
        help="comma-separated row counts, e.g. 100,1000,10000",
    )
    parser.add_argument(
        "--workers",
        default=None,
        help="comma-separated worker levels, e.g. 1,5,10,25,50,100",
    )
    parser.add_argument(
        "--concurrency-seconds",
        type=float,
        default=None,
        help="duration of each concurrency level",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="run the whole selection N times and report the median per metric",
    )
    parser.add_argument("--output-dir", default=None)
    parser.add_argument(
        "--replot",
        default=None,
        metavar="RESULTS_JSON",
        help="re-render the charts from a previous results.json and exit",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    config = BenchmarkConfig()

    overrides = {}

    if args.point_iterations:
        overrides["point_iterations"] = args.point_iterations

    if args.write_iterations:
        overrides["write_iterations"] = args.write_iterations

    if args.write_batch_size:
        overrides["write_batch_size"] = args.write_batch_size

    if args.write_commit_modes:
        overrides["write_commit_modes"] = [
            x.strip() for x in args.write_commit_modes.split(",") if x.strip()
        ]

    if args.result_set_iterations:
        overrides["result_set_iterations"] = args.result_set_iterations

    if args.result_set_sizes:
        overrides["result_set_sizes"] = [
            int(x) for x in args.result_set_sizes.split(",") if x.strip()
        ]

    if args.workers:
        overrides["worker_levels"] = [
            int(x) for x in args.workers.split(",") if x.strip()
        ]

    if args.concurrency_seconds:
        overrides["concurrency_seconds"] = args.concurrency_seconds

    if args.output_dir:
        overrides["output_dir"] = Path(args.output_dir)

    if overrides:
        config = replace(config, **overrides)

    if args.replot:
        import json

        from . import charts, report

        payload = json.loads(Path(args.replot).read_text(encoding="utf-8"))
        results = payload["results"]

        report.print_tables(results)

        for path in charts.render_all(results, config.output_dir):
            print(f"PNG:  {path}")

        return

    driver_names = [x.strip() for x in args.drivers.split(",") if x.strip()]
    selected = [x.strip() for x in args.scenarios.split(",") if x.strip()]

    unknown = [s for s in selected if s not in SCENARIOS]

    if unknown:
        raise SystemExit(
            f"Unknown scenario(s): {', '.join(unknown)}. "
            f"Available: {', '.join(SCENARIOS)}"
        )

    run(config, driver_names, selected, repeats=max(1, args.repeat))


if __name__ == "__main__":
    main()
