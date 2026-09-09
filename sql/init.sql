IF DB_ID('benchmark') IS NULL
BEGIN
    CREATE DATABASE benchmark;
END
GO

USE benchmark;
GO

IF OBJECT_ID('dbo.users', 'U') IS NOT NULL
    DROP TABLE dbo.users;
GO

CREATE TABLE dbo.users
(
    id              INT IDENTITY(1,1) PRIMARY KEY,
    username        VARCHAR(100) NOT NULL,
    email           VARCHAR(255) NOT NULL,
    first_name      VARCHAR(100) NOT NULL,
    last_name       VARCHAR(100) NOT NULL,
    age             INT NOT NULL,
    country         VARCHAR(100) NOT NULL,
    balance         DECIMAL(18,2) NOT NULL,
    is_active       BIT NOT NULL,
    created_at      DATETIME2 NOT NULL
);
GO

-- Scratch table for the write scenario. Kept separate from dbo.users so the
-- read scenarios always see the same 100k rows, whatever the writes do.
IF OBJECT_ID('dbo.users_writes', 'U') IS NOT NULL
    DROP TABLE dbo.users_writes;
GO

CREATE TABLE dbo.users_writes
(
    id              INT IDENTITY(1,1) PRIMARY KEY,
    username        VARCHAR(100) NOT NULL,
    email           VARCHAR(255) NOT NULL,
    first_name      VARCHAR(100) NOT NULL,
    last_name       VARCHAR(100) NOT NULL,
    age             INT NOT NULL,
    country         VARCHAR(100) NOT NULL,
    balance         DECIMAL(18,2) NOT NULL,
    is_active       BIT NOT NULL,
    created_at      DATETIME2 NOT NULL
);
GO
