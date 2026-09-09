-- Set-based seed. Populates dbo.users with @rows rows in a handful of
-- statements instead of one INSERT per row, so a 100k seed takes seconds.
USE benchmark;
GO

DECLARE @rows INT = 100000;

;WITH n AS
(
    SELECT TOP (@rows)
        ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS i
    FROM sys.all_objects a
    CROSS JOIN sys.all_objects b
)
INSERT INTO dbo.users
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
SELECT
    CONCAT('user_', n.i),
    CONCAT('user_', n.i, '@example.com'),
    'John',
    'Doe',
    20 + (n.i % 50),
    CASE
        WHEN n.i % 3 = 0 THEN 'Brazil'
        WHEN n.i % 3 = 1 THEN 'USA'
        ELSE 'UK'
    END,
    (n.i % 10000) * 1.25,
    CASE
        WHEN n.i % 2 = 0 THEN 1
        ELSE 0
    END,
    DATEADD(DAY, -(n.i % 3650), SYSUTCDATETIME())
FROM n;
GO

-- Supporting index for the filtered/result-set scenarios.
IF NOT EXISTS
(
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_users_country_age'
      AND object_id = OBJECT_ID('dbo.users')
)
BEGIN
    CREATE INDEX IX_users_country_age
        ON dbo.users (country, age);
END
GO

SELECT
    COUNT(*) AS seeded_rows
FROM dbo.users;
GO
