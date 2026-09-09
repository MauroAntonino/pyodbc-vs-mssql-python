# pyodbc vs mssql-python

**The goal of this repository is to compare
[pyodbc](https://github.com/mkleehammer/pyodbc) with
[mssql-python](https://github.com/microsoft/mssql-python) — the two Python
drivers for SQL Server — by measuring both under the same workloads, on the same
database, in the same run.**

Four workloads are measured across four scenarios. Everything runs in Docker, so
the numbers can be reproduced on another machine.

## Environment

Every value below was produced on this setup, recorded automatically in
`results/results.json` → `metadata`:

| | |
|---|---|
| Database | SQL Server 2022 CU26 Developer, in a container |
| Server resources | 32 vCPUs visible, 12.4 GB RAM |
| Client | `python:3.12-slim`, **same host** as the database |
| Host | Windows 11, Docker Desktop / WSL2 |
| Drivers | pyodbc 5.3.0 + `ODBC Driver 18` (msodbcsql18 18.6.2.1) · mssql-python 1.14.0 |
| Connection | `Encrypt=no`, `TrustServerCertificate=yes`, autocommit unless stated |
| Table | `dbo.users`, 10 columns, 100,000 rows |
| Runs | 3 full runs; every table reports the median per metric |

All four scenarios select or write the same ten columns: `id`, `username`,
`email`, `first_name`, `last_name`, `age`, `country`, `balance`, `is_active`,
`created_at`.

## How to run it

```bash
docker compose up -d --wait sqlserver
```

```bash
docker compose run --rm db-init
```

```bash
docker compose run --rm --no-deps benchmark --repeat 3
```

Output goes to `results/`: charts (`.png`), raw numbers (`results.json`, which
also keeps each individual run), and a `results.csv`. See `--help` for the flags
that change any parameter below.

## Overview

![benchmark](results/benchmark-light.png)

---

## Scenario 1 — One row at a time

**Configuration**

| | |
|---|---|
| Query | `SELECT <10 columns> FROM dbo.users WHERE id = ?` |
| Iterations | 10,000 |
| Connections | 1, reused for every iteration |
| Cursor | 1, reused; `fetchone()` after each execute |
| Row ids | random within 1–100,000, fixed seed (same sequence for both drivers) |
| Warmup | 100 queries before the clock starts |
| Timing | per statement: `execute` + `fetchone` |

**Results**

| Driver | queries/sec | avg | p50 | p95 | p99 |
|---|---|---|---|---|---|
| pyodbc | 5,694 | 0.175 ms | 0.165 ms | 0.228 ms | 0.293 ms |
| mssql-python | 3,887 | 0.256 ms | 0.244 ms | 0.327 ms | 0.396 ms |

**Better:** pyodbc, 1.46x higher throughput.
**Worse:** mssql-python, 0.081 ms more per query on average.

---

## Scenario 2 — Many rows at once

**Configuration**

| | |
|---|---|
| Query | `SELECT TOP (N) <10 columns> FROM dbo.users WHERE id >= ? ORDER BY id` |
| Sizes (N) | 100, 1,000, 10,000 |
| Iterations | 200 per size |
| Connections | 1, reused |
| Fetch | `fetchall()` — the whole result set is materialized |
| Starting id | random, fixed seed per size |
| Warmup | 100 point queries, plus one priming query per size |
| Timing | per statement: `execute` + `fetchall` |

**Results**

| Rows per query | Driver | rows/sec | queries/sec | avg | p95 | p99 |
|---|---|---|---|---|---|---|
| 100 | pyodbc | 197,559 | 1,976 | 0.505 ms | 0.617 ms | 0.742 ms |
| 100 | mssql-python | 177,999 | 1,780 | 0.561 ms | 0.661 ms | 0.697 ms |
| 1,000 | pyodbc | 340,842 | 341 | 2.932 ms | 3.176 ms | 3.458 ms |
| 1,000 | mssql-python | 479,111 | 479 | 2.086 ms | 2.514 ms | 3.939 ms |
| 10,000 | pyodbc | 348,131 | 35 | 28.718 ms | 30.118 ms | 31.023 ms |
| 10,000 | mssql-python | 573,948 | 57 | 17.419 ms | 20.989 ms | 22.122 ms |

**Better:** pyodbc at 100 rows (1.11x); mssql-python at 1,000 rows (1.41x) and at
10,000 rows (1.65x).
**Worse:** the two swap places between 100 and 1,000 rows. The 100-row margin
also moved between runs (pyodbc ahead by 1.0x to 1.6x), so it is the least stable
figure on this page.

---

## Scenario 3 — Threads

**Configuration**

| | |
|---|---|
| Query | same as scenario 1 |
| Thread counts | 1, 5, 10, 25, 50, 100 |
| Connections | one per thread, opened before timing starts |
| Duration | 5 seconds per thread count (time-boxed, not a fixed iteration count) |
| Warmup | 20 queries per thread, before the clock |
| Start | a barrier releases all threads together; connection setup is excluded |
| Timing | per statement, aggregated across threads |

**Results**

| Threads | pyodbc qps | pyodbc p95 | mssql-python qps | mssql-python p95 |
|---|---|---|---|---|
| 1 | 5,595 | 0.24 ms | 3,820 | 0.33 ms |
| 5 | 2,891 | 3.31 ms | 7,203 | 2.13 ms |
| 10 | 1,345 | 9.00 ms | 6,957 | 2.85 ms |
| 25 | 1,318 | 22.78 ms | 6,982 | 8.98 ms |
| 50 | 1,316 | 45.91 ms | 6,922 | 25.89 ms |
| 100 | 1,314 | 90.65 ms | 6,709 | 45.17 ms |

**Better:** pyodbc at 1 thread (1.46x); mssql-python from 5 threads up (2.49x at
5, 5.17x at 10, 5.11x at 100).
**Worse:** pyodbc throughput falls as threads are added — 5,595 qps at 1 thread,
1,345 at 10 — and then stays flat from 10 to 100 threads while p95 rises roughly
in proportion to the thread count. mssql-python stays between 6,709 and 7,203 qps
across 5–100 threads.

**Two extra measurements on that pyodbc curve**

| Check | Result |
|---|---|
| ODBC connection pooling off (`DB_PYODBC_POOLING=false`) | unchanged: 1,338 qps at 10 threads, 1,299 at 100 |
| Two pyodbc processes, 10 threads each, at the same time | 1,186 + 1,258 ≈ 2,444 qps combined, vs ~1,300 qps from one process |

---

## Scenario 4 — Writes

**Configuration**

| | |
|---|---|
| Table | `dbo.users_writes` — same 10 columns, separate from `dbo.users` |
| Rows per phase | 5,000 |
| Phases, in order | INSERT row by row → INSERT `executemany` → UPDATE → DELETE |
| `executemany` batch | 1,000 rows per call |
| pyodbc `fast_executemany` | enabled (the JSON records this per run) |
| mssql-python `fast_executemany` | not exposed by the driver; recorded as `false` |
| UPDATE | `SET balance = ?, is_active = ? WHERE id = ?`, random ids, fixed seed |
| DELETE | `WHERE id = ?`, every inserted row |
| Commit mode A | `autocommit` — one commit per statement |
| Commit mode B | explicit transaction — one commit per 1,000 statements |
| Table state | truncated between phases; commit time is inside the measured window |

**Results — commit per statement (autocommit)**

| Operation | pyodbc rows/s | mssql-python rows/s |
|---|---|---|
| INSERT row by row | 802 | 812 |
| INSERT `executemany` | 1,013 | 1,038 |
| UPDATE by id | 813 | 878 |
| DELETE by id | 875 | 843 |

**Results — commit every 1,000 statements**

| Operation | pyodbc rows/s | mssql-python rows/s |
|---|---|---|
| INSERT row by row | 5,593 | 5,094 |
| INSERT `executemany` | 86,982 | 57,583 |
| UPDATE by id | 6,421 | 5,756 |
| DELETE by id | 6,739 | 6,065 |

**Better:** with commit per statement, the two are within 8% of each other in
both directions (mssql-python ahead on INSERT and UPDATE, pyodbc ahead on
DELETE). With batched commits, pyodbc is ahead on all four operations: 1.10x
(INSERT row by row), **1.51x** (INSERT `executemany`), 1.12x (UPDATE), 1.11x
(DELETE).
**Worse:** in autocommit, every operation for both drivers stays between 802 and
1,038 rows/s, including `executemany`. The same operations reach 5,094–86,982
rows/s once commits are batched.

Note on scope: only APIs available in both drivers are compared, so the batch row
is `executemany`. mssql-python also provides `cursor.bulkcopy()`, which is faster
than anything on this page, and pyodbc has no equivalent.

---