# pyodbc vs mssql-python

Which Python driver is faster against SQL Server? We measured it. Everything runs
in Docker, so you can repeat it on your own machine.

## Short answer

| If your app... | Use | Why |
|---|---|---|
| runs queries in threads | **mssql-python** | 5x faster from 10 threads up |
| reads big result sets | **mssql-python** | 1.7x faster at 10,000 rows |
| runs small queries, one at a time | **pyodbc** | 1.5x faster per query |
| bulk-inserts with `executemany` | **pyodbc** | 1.5x faster |

The biggest single finding: **pyodbc gets slower when you add threads.** One
thread does 5,600 queries/sec; ten threads do 1,345 — worse than one. It then
stays flat no matter how many threads you add. mssql-python holds ~7,000
queries/sec from 1 to 100 threads.

## How to run it

Start the database:

```bash
docker compose up -d --wait sqlserver
```

Create the table and load 100,000 rows:

```bash
docker compose run --rm db-init
```

Run the benchmark:

```bash
docker compose run --rm --no-deps benchmark --repeat 3
```

That's it. Results appear in the `results/` folder: two charts (`.png`), the raw
numbers (`results.json`), and a spreadsheet-friendly copy (`results.csv`).

`--repeat 3` runs everything three times and reports the middle value, which
avoids drawing conclusions from one noisy run.

Want to change something? Try `--help`. Common ones:

```bash
docker compose run --rm --no-deps benchmark --scenarios concurrency --workers 1,10,50,200
```

## What gets measured

Four tests, both drivers, same database:

1. **One row at a time** — `SELECT ... WHERE id = ?`, repeated 10,000 times.
   Shows the fixed cost of a single query.
2. **Many rows at once** — `SELECT TOP 100 / 1000 / 10000`, read completely.
   Shows how fast each driver turns rows into Python objects.
3. **Threads** — the same one-row query, run by 1 to 100 threads at the same
   time. Shows what happens under load.
4. **Writes** — INSERT, UPDATE and DELETE, 5,000 rows each. Run twice: once
   committing every statement, once committing every 1,000.

## The numbers

Median of 3 runs.

![benchmark](results/benchmark-light.png)

### Reading

| Test | pyodbc | mssql-python | winner |
|---|---|---|---|
| One row at a time | **5,694 queries/s** | 3,887 queries/s | pyodbc, 1.5x |
| 100 rows | **197,559 rows/s** | 177,999 rows/s | pyodbc, 1.1x |
| 1,000 rows | 340,842 rows/s | **479,111 rows/s** | mssql-python, 1.4x |
| 10,000 rows | 348,131 rows/s | **573,948 rows/s** | mssql-python, 1.7x |
| 1 thread | **5,595 queries/s** | 3,820 queries/s | pyodbc, 1.5x |
| 10 threads | 1,345 queries/s | **6,957 queries/s** | mssql-python, 5.2x |
| 100 threads | 1,314 queries/s | **6,709 queries/s** | mssql-python, 5.1x |

### Writing (rows per second)

| Operation | commit every... | pyodbc | mssql-python | winner |
|---|---|---|---|---|
| INSERT, one row per statement | statement | 802 | 812 | tie |
| INSERT, `executemany` | statement | 1,013 | 1,038 | tie |
| UPDATE | statement | 813 | 878 | tie |
| DELETE | statement | 875 | 843 | tie |
| INSERT, one row per statement | 1,000 rows | **5,593** | 5,094 | pyodbc, 1.1x |
| INSERT, `executemany` | 1,000 rows | **86,982** | 57,583 | pyodbc, 1.5x |
| UPDATE | 1,000 rows | **6,421** | 5,756 | pyodbc, 1.1x |
| DELETE | 1,000 rows | **6,739** | 6,065 | pyodbc, 1.1x |

**About writes:** notice the top half of that table. When you commit after every
statement, both drivers do about 800–1,000 rows/sec and the driver stops
mattering — the database is waiting on its log file, not on Python. Commit in
batches instead and the same work runs about 7x faster. If your writes are slow,
this is worth checking before you change drivers.

## Why pyodbc slows down with threads

We tested two explanations:

- **Connection pooling?** No. pyodbc turns it on by default; turning it off
  (`DB_PYODBC_POOLING=false`) changes nothing.
- **Is the database the limit?** No. We ran two separate pyodbc processes with 10
  threads each, at the same time. Each got ~1,200 queries/sec, so together
  ~2,400 — double. The limit is inside each Python process, not in SQL Server.

So the bottleneck is somewhere in pyodbc or in the ODBC layer under it. We think
it is the shared ODBC environment handle and the lock around it, but we did not
prove that — we only proved the limit is per process.

**What this means in practice:** pyodbc's advantage on single queries disappears
as soon as your app uses threads. To scale pyodbc you need multiple processes.

## Things to keep in mind

- The client and the database run on the **same machine**, so network delay is
  near zero. This makes driver overhead look bigger than it would in production.
  On a real network the two drivers would be closer. Benchmarks run against a
  remote database (like Azure SQL) can reach different conclusions for this
  reason, and that is not a contradiction.
- SQL Server runs in Docker on Windows (WSL2), so the absolute numbers depend on
  that. The comparison between the two drivers is the useful part, not the raw
  values.
- The "100 rows" result is the least stable one. Across runs we saw pyodbc ahead
  by anywhere from 1.0x to 1.6x. Read it as "about the same", not as an exact
  figure.
- Only features that both drivers have are compared. mssql-python also has
  `cursor.bulkcopy()`, which is faster than everything measured here, but pyodbc
  has no equivalent, so including it would not be a fair comparison.
- Three runs is better than one, but it is not a statistical study.

## Setup measured

- SQL Server 2022 CU26 Developer, in a container
- Client: `python:3.12-slim`, same host, Docker Desktop / WSL2
- pyodbc 5.3.0 with `ODBC Driver 18`; mssql-python 1.14.0
- One table, 10 columns, 100,000 rows

The exact environment of every run is saved inside `results.json`.
