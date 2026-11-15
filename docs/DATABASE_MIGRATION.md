# AgentHQ Database Migration Guide

**Document Version:** 1.0 (Phase 2A)  
**Applies To:** Local SQLite & Neon Serverless PostgreSQL  
**Tooling:** Alembic & SQLAlchemy 2.0  

---

## 1. Migration System Overview

AgentHQ manages database versioning and schema migrations using **Alembic**. The migration configuration is located in the `backend/` directory:

```text
backend/
├── alembic.ini                   # Alembic runtime configuration
├── alembic/
│   ├── env.py                    # Migration execution environment (auto-selects engine)
│   ├── script.py.mako            # Migration template
│   └── versions/
│       └── 0001_initial_schema.py # Initial baseline migration & dual-dialect schema
```

### Key Capabilities
* **Dual-Dialect Compatibility:** Migrations run natively on both SQLite (with `render_as_batch=True`) and PostgreSQL.
* **Pre-Existing Database Preservation:** `0001_initial_schema.py` inspects existing tables before executing `CREATE TABLE`. If an older SQLite database is present, it safely alters `conversation_messages` to add `order_index`, backfills `order_index = rowid`, and stamps the version without data loss.
* **Idempotent Employee Seeding:** Canonical AI employees are seeded automatically if absent, without overwriting custom edits.

---

## 2. Standard Migration Commands

All migration commands should be run from the `backend/` directory with the virtual environment active.

### 2.1 Apply Migrations (Upgrade to Head)
Applies all pending migrations up to the latest revision:

```powershell
Set-Location E:\AgentHQ\backend
.\.venv\Scripts\alembic.exe upgrade head
```

On Linux / Render:
```bash
cd backend
alembic upgrade head
```

### 2.2 Inspect Migration Status
View the currently applied revision in the active database:

```powershell
.\.venv\Scripts\alembic.exe current
```

View the migration history:

```powershell
.\.venv\Scripts\alembic.exe history --verbose
```

### 2.3 Rollback Migrations (Downgrade)
Roll back by one revision:

```powershell
.\.venv\Scripts\alembic.exe downgrade -1
```

Roll back all migrations (drop all managed tables):

```powershell
.\.venv\Scripts\alembic.exe downgrade base
```

### 2.4 Stamp an Existing Database
If a database already has the schema created and needs its version counter synchronized to head without re-executing DDL:

```powershell
.\.venv\Scripts\alembic.exe stamp head
```

---

## 3. Local SQLite Workflow

In local development, AgentHQ defaults to SQLite:
1. When starting the API via `backend/run.ps1` or `app.main:app`, FastAPI's lifespan calls `db.init_db()`.
2. `db.init_db()` verifies table existence, applies missing columns (such as `order_index`), and seeds canonical employees.
3. To manually run migrations against a specific SQLite database:
   ```powershell
   $env:AGENTHQ_DB_PATH = "E:\AgentHQ\backend\data\custom.db"
   .\.venv\Scripts\alembic.exe upgrade head
   ```

---

## 4. Cloud PostgreSQL (Neon) Deployment Workflow

When deploying AgentHQ to Render:
1. Provide the Neon pooled connection string via the `DATABASE_URL` environment variable:
   ```text
   DATABASE_URL=postgresql://user:password@ep-sample-pooler.us-east-2.aws.neon.tech/agenthq?sslmode=require
   ```
2. Render's build command automatically executes Alembic:
   ```bash
   pip install -r backend/requirements.txt && alembic upgrade head
   ```
3. `env.py` reads `DATABASE_URL`, normalizes it to use `psycopg 3`, establishes a connection pool, and executes `0001_initial_schema.py`.
4. *Important:* No manual migrations against the live Neon database are required during local development. Migrations are executed securely during cloud build/deploy.

---

## 5. Backup & Restore Procedures

### 5.1 Local SQLite Backup & Restore

#### Creating a Backup:
```powershell
# Safe file copy (NullPool ensures zero active locks)
Copy-Item "E:\AgentHQ\backend\data\agenthq.db" "E:\AgentHQ\backend\data\agenthq.db.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

#### Restoring from Backup:
```powershell
# Stop the FastAPI server, then replace the database file:
Copy-Item "E:\AgentHQ\backend\data\agenthq.db.backup-20261114-100000" "E:\AgentHQ\backend\data\agenthq.db" -Force
```

### 5.2 Neon PostgreSQL Backup & Restore

#### Creating a PostgreSQL Backup (`pg_dump`):
```bash
pg_dump "$DATABASE_URL" -F c -b -v -f "agenthq_neon_backup.dump"
```

#### Restoring to Neon:
```bash
pg_restore -d "$DATABASE_URL" -v --clean "agenthq_neon_backup.dump"
```

---

## 6. Testing Procedures

The modernized database layer includes an extensive automated test suite that runs **100% locally without requiring any cloud or Neon credentials**.

To run all database and API tests:

```powershell
$env:PYTHONPATH = "E:\AgentHQ\backend"
.\.venv\Scripts\python.exe -m unittest discover -s E:\AgentHQ\backend\tests -p "test_*.py"
```

### Test Coverage Highlights
* **Fresh SQLite Initialization:** Validates schema creation on completely empty files.
* **Canonical Employee Seeding:** Asserts all 7 founding employees are present.
* **Idempotency & Customization Safety:** Proves existing status and task edits are never overwritten.
* **Deterministic Ordering:** Proves messages created in the exact same second retain strict chronological order via `order_index`.
* **Foreign Key Cascade:** Asserts tasks revert `assigned_agent_id` to `NULL` upon agent deletion, and messages cascade on conversation deletion.
* **Alembic Verification:** Runs automated migration and version checks against isolated temporary databases.

