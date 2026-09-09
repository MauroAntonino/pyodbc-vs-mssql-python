"""Driver adapters.

Each driver is reduced to a name plus a zero-argument connection factory, so the
scenarios never branch on which library they are exercising.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .config import DatabaseConfig


class Connection(Protocol):
    def cursor(self): ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class Driver:
    name: str
    connect: Callable[[], Connection]


def _pyodbc_factory(db: DatabaseConfig) -> Callable[[], Connection]:
    import os

    import pyodbc

    # pyodbc enables ODBC Driver Manager connection pooling by default, which
    # serializes on a shared lock and dominates the concurrency scenario. This
    # must be set before the first connection is opened.
    if os.getenv("DB_PYODBC_POOLING", "true").lower() in {"0", "false", "no"}:
        pyodbc.pooling = False

    connection_string = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={db.host},{db.port};"
        f"DATABASE={db.database};"
        f"UID={db.user};"
        f"PWD={db.password};"
        f"Encrypt={db.encrypt};"
        f"TrustServerCertificate={db.trust_server_certificate};"
    )

    def connect() -> Connection:
        return pyodbc.connect(connection_string, autocommit=True)

    return connect


def _mssql_python_factory(db: DatabaseConfig) -> Callable[[], Connection]:
    from mssql_python import connect as mssql_connect

    connection_string = (
        f"Server={db.host},{db.port};"
        f"Database={db.database};"
        f"UID={db.user};"
        f"PWD={db.password};"
        f"Encrypt={db.encrypt};"
        f"TrustServerCertificate={db.trust_server_certificate};"
    )

    def connect() -> Connection:
        # Older mssql-python builds do not accept the autocommit kwarg; fall
        # back to setting the attribute so both paths stay comparable.
        try:
            return mssql_connect(connection_string, autocommit=True)
        except TypeError:
            conn = mssql_connect(connection_string)
            try:
                conn.autocommit = True
            except Exception:
                pass
            return conn

    return connect


_FACTORIES: dict[str, Callable[[DatabaseConfig], Callable[[], Connection]]] = {
    "pyodbc": _pyodbc_factory,
    "mssql-python": _mssql_python_factory,
}

ALL_DRIVER_NAMES = tuple(_FACTORIES)


def build_drivers(db: DatabaseConfig, names: list[str] | None = None) -> list[Driver]:
    """Instantiate the requested drivers, skipping any that fail to import."""
    selected = names or list(ALL_DRIVER_NAMES)

    drivers: list[Driver] = []

    for name in selected:
        factory = _FACTORIES.get(name)

        if factory is None:
            raise SystemExit(
                f"Unknown driver {name!r}. Available: {', '.join(ALL_DRIVER_NAMES)}"
            )

        try:
            drivers.append(Driver(name=name, connect=factory(db)))
        except ImportError as exc:
            print(f"[skip] driver {name} unavailable: {exc}")

    if not drivers:
        raise SystemExit("No usable driver found.")

    return drivers
