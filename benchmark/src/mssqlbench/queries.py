"""SQL used by the scenarios. All ten columns are always projected."""

COLUMNS = """
    id,
    username,
    email,
    first_name,
    last_name,
    age,
    country,
    balance,
    is_active,
    created_at
"""

POINT_SELECT = f"""
SELECT
{COLUMNS}
FROM dbo.users
WHERE id = ?
"""

# Same order as COLUMNS. Sliced by the profiling scenario to vary how many
# columns a single row carries: index 0 alone is a bare INT.
POINT_COLUMNS = [
    "id",
    "username",
    "email",
    "first_name",
    "last_name",
    "age",
    "country",
    "balance",
    "is_active",
    "created_at",
]


def point_select_query(columns: int, variant: int | None = None) -> str:
    """Point select projecting the first `columns` columns.

    `variant` appends a comment, which changes the SQL text without changing
    the query. Used to check whether either driver benefits from seeing the
    exact same statement text on every call.
    """
    selected = ", ".join(POINT_COLUMNS[:columns])

    suffix = f" -- variant {variant}" if variant is not None else ""

    return f"SELECT {selected} FROM dbo.users WHERE id = ?{suffix}"


WRITE_TABLE = "dbo.users_writes"

TRUNCATE_WRITES = f"TRUNCATE TABLE {WRITE_TABLE}"

WRITE_IDS = f"SELECT id FROM {WRITE_TABLE} ORDER BY id"

INSERT_ROW = f"""
INSERT INTO {WRITE_TABLE}
(
    username,
    email,
    first_name,
    last_name,
    age,
    country,
    balance,
    is_active,
    created_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# Two columns of different types, so the update is not a no-op rewrite.
UPDATE_ROW = f"""
UPDATE {WRITE_TABLE}
SET balance = ?,
    is_active = ?
WHERE id = ?
"""

DELETE_ROW = f"""
DELETE FROM {WRITE_TABLE}
WHERE id = ?
"""


def result_set_query(top: int) -> str:
    # TOP takes a literal here on purpose: each result-set size should get its
    # own cached plan, so plan reuse is not part of what we are measuring.
    return f"""
SELECT TOP ({top})
{COLUMNS}
FROM dbo.users
WHERE id >= ?
ORDER BY id
"""
