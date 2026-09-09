FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    MPLCONFIGDIR=/tmp/matplotlib

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    ca-certificates \
    gcc \
    g++ \
    unixodbc \
    unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

# Microsoft package repository
RUN curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
    | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg

RUN curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list \
    -o /etc/apt/sources.list.d/mssql-release.list

# msodbcsql18 is the ODBC driver pyodbc talks through; mssql-python ships its
# own client, so this is exactly the asymmetry under test.
RUN apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

ENTRYPOINT ["python", "-m", "mssqlbench"]
