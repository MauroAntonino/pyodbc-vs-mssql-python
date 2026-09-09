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


WRITE_TABLE = "dbo.users_writes"

TRUNCATE_WRITES = f"TRUNCATE TABLE {WRITE_TABLE}"

<<<<<<< HEAD
=======
# The nine insertable columns, in the order _write_row() produces them. Needed
# by bulk-copy APIs, which map by ordinal position and would otherwise try to
# write the IDENTITY column.
WRITE_COLUMNS = [
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

>>>>>>> 457dadfb7dccac1633abd9745d5b5a7853abef11
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
