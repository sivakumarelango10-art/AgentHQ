# Security State Database Migration Guide (Phase 2D.1)

**Revision ID:** `0003_persistent_security_state`  
**Revises:** `0002_daily_ai_usage`  
**Target Engines:** SQLite 3.50+ & Neon PostgreSQL  

---

## 1. Migration Overview

Phase 2D.1 migrates transient in-memory security state into the persistent SQLAlchemy database.

### New Database Tables
1. `owner_sessions`: Session token hashes, CSRF token hashes, expiration, and revocation status.
2. `login_attempts`: Rate-limiting history indexed by IP address and timestamp.
3. `websocket_tickets`: Single-use tickets indexed by SHA-256 hash.

### Existing Tables Preserved
The migration is additive and strictly non-destructive. The following existing tables are left untouched:
- `agents` (canonical and custom employee records)
- `tasks` (kanban and autonomous task records)
- `conversations` (chat history threads)
- `conversation_messages` (ordered dialog turns)
- `runtime_sessions` (Hermes3D-to-AgentHQ session mappings)
- `daily_ai_usage` (model-specific token and neuron telemetry)
- `daily_ai_quota_buckets` (provider-level daily quota ceiling)

---

## 2. Pre-Migration Verification & Backup

Before executing database schema updates, back up the active SQLite database:

```powershell
# PowerShell backup
Copy-Item E:\AgentHQ\backend\data\agenthq.db E:\AgentHQ\backend\data\agenthq.db.backup-phase2d1
```

---

## 3. Applying the Migration

### Local Development (SQLite)
From `E:\AgentHQ\backend`:

```powershell
.\.venv\Scripts\python -m alembic upgrade head
```

Expected Output:
```text
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 0002_daily_ai_usage -> 0003_persistent_security_state, Create persistent security state tables: owner_sessions, login_attempts, websocket_tickets.
```

### Production Cloud Deployment (Neon PostgreSQL)
When deploying to Render/Neon, ensure `DATABASE_URL` is set, then execute:

```bash
python -m alembic upgrade head
```

Alembic will detect `PostgresqlImpl`, transactional DDL will be enabled, and all indices, unique constraints, and foreign keys will be created atomically.

---

## 4. Verification Commands

Verify that the active migration version is `0003_persistent_security_state`:

```powershell
# Verify migration version in SQLite
.\.venv\Scripts\python -c "import sqlite3; c = sqlite3.connect('data/agenthq.db'); print('Current Alembic Version:', c.execute('SELECT version_num FROM alembic_version').fetchone()[0])"
```

Verify that all tables exist:

```powershell
.\.venv\Scripts\python -c "import sqlite3; c = sqlite3.connect('data/agenthq.db'); print('Tables:', [r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()])"
```

Expected Table List:
`['agents', 'tasks', 'conversations', 'conversation_messages', 'runtime_sessions', 'alembic_version', 'daily_ai_usage', 'daily_ai_quota_buckets', 'owner_sessions', 'login_attempts', 'websocket_tickets']`

---

## 5. Rollback & Downgrade Plan

If a rollback is required, downgrade to revision `0002_daily_ai_usage`:

```powershell
.\.venv\Scripts\python -m alembic downgrade -1
```

Expected Output:
```text
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running downgrade 0003_persistent_security_state -> 0002_daily_ai_usage, Create persistent security state tables: owner_sessions, login_attempts, websocket_tickets.
```

The downgrade safely drops the indices and tables for `websocket_tickets`, `login_attempts`, and `owner_sessions` without altering any agent or conversation data.

