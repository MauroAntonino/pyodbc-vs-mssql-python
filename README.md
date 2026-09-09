# pyodbc vs mssql-python

A reproducible benchmark of the two Python drivers for SQL Server, across four
scenarios: point lookup, result-set transport, concurrency, and writes.

We built it to pick a driver for our own Python services instead of deciding on
intuition. It is not a verdict on which driver is better — it is one environment,
measured, with the environment recorded next to the numbers. **We are looking for
feedback on the configuration:** if an option of ours is under-serving either
driver, the number is wrong and we want to fix it.

## Run it

```bash
docker compose up -d --wait sqlserver
```

```bash
docker compose run --rm db-init
```

```bash
docker compose run --rm --no-deps benchmark --repeat 3
```

Results land in `results/`: `results.json` (canonical, with full metadata),
`results.csv`, and the charts below. `--repeat 3` reports the median per metric
and keeps each individual run in the JSON.

Useful flags: `--scenarios`, `--drivers`, `--workers 1,10,50,200`,
`--concurrency-seconds`, `--point-iterations`, `--write-iterations`,
`--replot results.json` (re-render charts only). Full list: `--help`.

## Setup

- SQL Server 2022 CU26 Developer in a container (32 vCPUs visible, 12.4 GB)
- Client `python:3.12-slim` on the same host — Docker Desktop / WSL2
- pyodbc 5.3.0 + `ODBC Driver 18`, mssql-python 1.14.0
- `dbo.users`, 10 columns, 100k rows

Only APIs that exist on both drivers are compared, so the batch row is
`executemany` (with pyodbc's `fast_executemany` enabled). mssql-python also ships
`cursor.bulkcopy()`, faster than anything here, but pyodbc has no equivalent — it
is deliberately out of scope rather than reported as a head-to-head win.

## Results

Median of 3 runs.

![benchmark](results/benchmark-light.png)

### Reads

| Case | pyodbc | mssql-python | relative |
|---|---|---|---|
| Point select | 5,694 qps · p95 0.228 ms | 3,887 qps · p95 0.327 ms | 0.68x |
| TOP 100 | 197,559 rows/s | 177,999 rows/s | 0.90x |
| TOP 1000 | 340,842 rows/s | 479,111 rows/s | **1.41x** |
| TOP 10000 | 348,131 rows/s | 573,948 rows/s | **1.65x** |
| 1 worker | 5,595 qps | 3,820 qps | 0.68x |
| 10 workers | 1,345 qps | 6,957 qps | **5.17x** |
| 100 workers | 1,314 qps · p95 90.6 ms | 6,709 qps · p95 45.2 ms | **5.11x** |

### Writes (5,000 rows per phase, `rows/s`)

| Operation | commit | pyodbc | mssql-python | relative |
|---|---|---|---|---|
| INSERT row by row | autocommit | 802 | 812 | 1.01x |
| INSERT executemany | autocommit | 1,013 | 1,038 | 1.02x |
| UPDATE by id | autocommit | 813 | 878 | 1.08x |
| DELETE by id | autocommit | 875 | 843 | 0.96x |
| INSERT row by row | tx/1000 | 5,593 | 5,094 | 0.91x |
| INSERT executemany | tx/1000 | **86,982** | 57,583 | 0.66x |
| UPDATE by id | tx/1000 | 6,421 | 5,756 | 0.90x |
| DELETE by id | tx/1000 | 6,739 | 6,065 | 0.90x |

## Findings

**Single-threaded small queries: pyodbc ahead** (~1.5x on the point select).
The `TOP 100` margin is the least stable number here — separate runs put it at
0.61x, 0.90x and 0.97x, so treat "pyodbc slightly ahead at 100 rows" as the
finding and not the figure.

**Large result sets: mssql-python ahead,** widening with size (1.41x at 1k,
1.65x at 10k).

**Writes: the commit dominates, not the driver.** Under autocommit everything
converges to ~800–1,000 rows/s and differences fall inside the noise in both
directions (0.96x–1.08x) — every statement pays a log flush. Under an explicit
transaction the same load runs ~7x faster and pyodbc leads across the board, by
1.51x on `executemany` (`fast_executemany` batches at the protocol level;
mssql-python does not expose that attribute).

**Concurrency: not a comparison, a ceiling.** pyodbc gets *worse* under load —
5,595 qps at 1 worker drops to ~1,345 qps from 10 workers onward, p95 growing
linearly to 91 ms at 100. A flat plateau with linear latency is a serialization
point, not server saturation: mssql-python sustains ~6,700–7,200 qps at every
level against the same server.

We tested two explanations for the plateau:

- **ODBC connection pooling** (`pyodbc.pooling`, on by default) — not the cause.
  `DB_PYODBC_POOLING=false` leaves the plateau unchanged.
- **Per process or server-side?** Two pyodbc containers with 10 threads each,
  simultaneously: 1,186 + 1,258 ≈ 2,444 qps. Doubling processes roughly doubled
  throughput, so the ceiling is **per process**, not SQL Server's.

Our hypothesis is the shared ODBC environment handle (pyodbc uses one `HENV` for
all connections) plus the unixODBC lock around it, with the GIL pattern as a
co-suspect — but that is a hypothesis, not a result. We did not instrument the
driver.

Practical consequence for us: pyodbc's per-statement advantage stops mattering
well before 10 threads.

## Feedback we're looking for

1. **pyodbc under concurrency.** Is there a setting — per-connection `HENV`,
   pooling, unixODBC threading level, `odbcinst.ini` — that removes the
   ~1,300 qps per-process plateau? If so, the 5.17x is measuring our
   configuration, not the driver.
2. **mssql-python when single-threaded.** The point select came out at 0.68x. Is
   there anything to enable (pooling, prepared statements, fetch buffers) that
   improves the small-query path?
3. **Scope of the batch comparison.** Is restricting it to `executemany` the
   right call, or is leaving `bulkcopy()` out more misleading than including it?
4. **Methodology.** ~0 latency amplifies driver overhead. Is a scenario with real
   network latency more valuable than more iterations?

Issues and PRs welcome. If you run this elsewhere, `results.json` carries the
full metadata — opening an issue with your file is already a useful contribution.

## Caveats

- **Client and server on the same host:** latency is ~0, which amplifies driver
  overhead. On a real network the numbers move closer together. This is the
  biggest difference from benchmarks run against Azure SQL, where latency
  dominates and conclusions can invert.
- **Docker Desktop / WSL2:** SQL Server runs virtualized. The ratios between
  drivers are more robust than the absolute values.
- **Median of 3 runs.** Better than one, far from a confidence interval.
- Every run overwrites `results/` — copy it first to keep a baseline.

## License

MIT.
