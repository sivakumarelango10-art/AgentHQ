# AgentHQ Unified Persistent Task Management Architecture (Phase 2D.2 & 2D.2.1)

## 1. System Overview & Authoritative Ownership

In the unified AgentHQ + Hermes3D architecture:
- **AgentHQ** is the **single authoritative source of truth** for all tasks, employee assignments, lifecycle state transitions, and audit records.
- **Hermes3D** serves as the browser client, interactive 3D pixel office, and Kanban board UI.
- **Neon PostgreSQL** is the authoritative production cloud database, while **local SQLite** is 100% supported for local development.

Under no circumstances does Hermes3D store divergent task state in production. All browser Kanban mutations pass through Hermes3D's server-side proxy route (`/api/task-store`), which securely connects to AgentHQ using authenticated server-to-server HTTP calls with `RUNTIME_API_TOKEN`.

```
+-------------------------------------------------------------------------------+
|                                  Browser UI                                   |
|                Hermes3D Kanban Board / 3D Office / Task Modals                |
+-------------------------------------------------------------------------------+
                                        |
                             HTTP /api/task-store
                                        v
+-------------------------------------------------------------------------------+
|                            Hermes3D Server Layer                              |
|            - Authenticates founder via studio_session cookie                  |
|            - Translates SharedTaskRecord <-> AgentHQ Task models              |
|            - Attaches RUNTIME_API_TOKEN in Authorization header               |
|            - Production: Fails closed on connection failure (502/503)         |
|            - Development: Local fallback ONLY if explicitly enabled           |
+-------------------------------------------------------------------------------+
                                        |
                       HTTP Bearer RUNTIME_API_TOKEN
                         /api/tasks & /api/tasks/{id}
                                        v
+-------------------------------------------------------------------------------+
|                               AgentHQ Runtime                                 |
|            - require_runtime_auth dependency (Bearer / Founder Session)       |
|            - Optimistic concurrency control (version field check -> 409)     |
|            - Status finite state machine enforcement (409 on invalid jump)    |
|            - Canonical employee assignment & role resolution (404 check)      |
|            - Exact timestamp semantics (completed_at vs cancelled_at)         |
|            - Immutable TaskAuditLog entry creation                            |
+-------------------------------------------------------------------------------+
                                        |
                           SQLAlchemy 2.0 ORM Engine
                                        v
+-------------------------------------------------------------------------------+
|                      Persistent Database (Neon / SQLite)                      |
|            - tasks: metadata, due dates, sources, version, check constraints  |
|            - task_audit_logs: chronological audit records (CASCADE FK)        |
|            - agents: canonical employees (ceo, pm, dev, design, etc.)        |
+-------------------------------------------------------------------------------+
```

---

## 2. Authoritative Data Model & Migrations

### 2.1 Database Schema (`tasks` table)

The `tasks` table stores the persistent task records. Schema migrations are managed via Alembic:
- `0004_unified_task_management.py`: Initial metadata, due dates, and audit tables.
- `0005_task_lifecycle_and_concurrency.py`: Exact timestamp semantics (`cancelled_at`) and optimistic concurrency versioning (`version`).

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| `id` | `VARCHAR(64)` | No | PK | Unique task identifier (UUID or custom client ID) |
| `title` | `VARCHAR(255)` | No | - | Required non-empty task title |
| `description` | `TEXT` | No | `""` | Detailed description or context |
| `priority` | `VARCHAR(20)` | No | `'normal'` | `'low'`, `'normal'`, `'high'`, `'urgent'` |
| `status` | `VARCHAR(20)` | No | `'queued'` | Canonical status (normalized to `'inbox'` on board) |
| `assigned_agent_id` | `VARCHAR(64)` | Yes | `NULL` | FK -> `agents.id` (ON DELETE SET NULL) |
| `due_date` | `VARCHAR(40)` | Yes | `NULL` | Target ISO-8601 due date |
| `completed_at` | `VARCHAR(40)` | Yes | `NULL` | ISO-8601 timestamp populated **only** when `status == "done"` |
| `cancelled_at` | `VARCHAR(40)` | Yes | `NULL` | ISO-8601 timestamp populated **only** when `status == "cancelled"` |
| `version` | `INTEGER` | No | `1` | Monotonically increasing version for optimistic concurrency |
| `source` | `VARCHAR(40)` | No | `'hermes3d_manual'` | Origin identifier (`'hermes3d_manual'`, `'agent_initiative'`) |
| `source_event_id` | `VARCHAR(120)` | Yes | `NULL` | Upstream correlation event ID |
| `created_at` | `VARCHAR(40)` | No | - | ISO-8601 UTC creation timestamp |
| `updated_at` | `VARCHAR(40)` | No | - | ISO-8601 UTC last update timestamp |

### 2.2 Audit History Schema (`task_audit_logs` table)

Every state transition, assignment change, or modification automatically records an immutable audit record:

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | `VARCHAR(64)` | No | Primary key UUID |
| `task_id` | `VARCHAR(64)` | No | FK -> `tasks.id` (ON DELETE CASCADE) |
| `action` | `VARCHAR(40)` | No | `'created'`, `'status_changed'`, `'assigned'`, `'updated'`, `'cancelled'` |
| `from_status` | `VARCHAR(40)` | Yes | Prior status |
| `to_status` | `VARCHAR(40)` | Yes | New status |
| `from_agent_id` | `VARCHAR(64)` | Yes | Prior assigned employee ID |
| `to_agent_id` | `VARCHAR(64)` | Yes | New assigned employee ID |
| `note` | `TEXT` | Yes | Human or system note describing the change |
| `actor` | `VARCHAR(80)` | Yes | Principal initiating the change (e.g. `'founder'`) |
| `at` | `VARCHAR(40)` | No | ISO-8601 UTC timestamp of the audit entry |

Indexes:
- `idx_task_audit_logs_task_id`: Fast retrieval of task audit trails.
- `idx_task_audit_logs_task_at`: Chronological ordering by task and timestamp.

---

## 3. Canonical Employee Integrity & Role Resolution

AgentHQ enforces strict employee integrity. Clients cannot assign arbitrary strings or invent non-existent employee roles.

### 3.1 The Seven Canonical Employees
The canonical founding employees are persisted in the `agents` table:

1. **`ceo`**: Atlas — *AI Orchestrator* (Management)
2. **`pm`**: Mira — *Project Manager* (Management)
3. **`dev`**: Arin — *Software Engineer* (Engineering)
4. **`kiran`**: Kiran — *Software Engineer* (Engineering)
5. **`design`**: Nia — *UI/UX Designer* (Design)
6. **`research`**: Ira — *Research Analyst* (Research)
7. **`qa`**: Dev — *QA Engineer* (Quality & Testing)

### 3.2 Assignment Rules
- **Validation**: Any assignment (`assigned_agent_id`) is validated against the `agents` database table. Attempting to assign an unknown ID fails immediately with `404 Not Found` (`"The selected employee does not exist."`).
- **Resolution**: Responses automatically resolve and output `assigned_agent_name` and `assigned_agent_role` directly from the employee record.
- **Unassignment**: Setting `assigned_agent_id: None` detaches the employee, sets name and role to `None`, and writes an `"assigned"` (unassigned) audit record.

---

## 4. Status State Machine & Exact Timestamp Semantics

Tasks follow a deterministic Finite State Machine (FSM):

```
                  +---------------------------+
                  |      INBOX / QUEUED       | <------+
                  +---------------------------+        |
                    |           |         ^            | (reopen)
                    v           |         |            |
             +-----------+      |         |            |
             | SCHEDULED |      |         |            |
             +-----------+      |         |            |
                    |           |         |            |
                    v           v         |            |
                  +---------------------------+        |
                  |          WORKING          | -------+
                  +---------------------------+
                    |           ^         ^
                    v           |         |
             +------------------+         |
             | NEEDS_ATTENTION  |         |
             +------------------+         |
                    |                     |
                    v (resolve)           |
                  +---------------------------+
                  |           DONE            |
                  +---------------------------+
                                |
                                v
                    +-----------------------+
                    |       CANCELLED       |  (Terminal State)
                    +-----------------------+
```

### 4.1 Allowed Transitions
- **`inbox` / `queued`**: $\to$ `scheduled`, `working`, `cancelled`
- **`scheduled`**: $\to$ `working`, `inbox`, `cancelled`
- **`working`**: $\to$ `needs_attention`, `done`, `inbox`, `cancelled`
- **`needs_attention`**: $\to$ `working`, `inbox`, `cancelled`
- **`done`**: $\to$ `working` (reopen), `inbox` (reopen)
- **`cancelled`**: **Terminal** (no transitions away from cancelled are permitted)

### 4.2 Exact Timestamp Semantics
- **`completed_at`**: Populated with the current UTC timestamp **only** when a task transitions to `done`. If a completed task is subsequently reopened to `working` or `inbox`, `completed_at` is cleared back to `None`.
- **`cancelled_at`**: Populated with the current UTC timestamp **only** when a task is cancelled. `completed_at` remains `None`.
- **Terminal Cancellation**: Any attempt to update, rename, or transition a cancelled task is rejected with `409 Conflict` (`"Cannot modify a cancelled task. Cancelled tasks are terminal."`).
- **Cancellation Idempotency**: Calling `/api/tasks/{id}/cancel` on an already cancelled task succeeds idempotently and returns the cancelled record with `cancelled_at` intact.

---

## 5. Concurrency Strategy: Optimistic Concurrency Control (OCC)

To prevent lost updates, race conditions, and stale writes across concurrent sessions:
1. Every task carries an integer `version` field starting at `1`.
2. Every committed modification (`PATCH /api/tasks/{task_id}` or cancellation) atomically increments `version = version + 1`.
3. Clients sending `PATCH /api/tasks/{task_id}` may include the `version` they based their update upon.
4. If `payload.version` is provided and does not match the current database `task.version`, AgentHQ rejects the update with `409 Conflict`:
   ```json
   {
     "detail": "Conflict: Task version mismatch (expected 1, current 2)."
   }
   ```
5. Hermes3D's `/api/task-store` propagates this `409 Conflict` directly to the client, preventing silent overwrites and prompting the client UI to refresh latest state.

---

## 6. API Request Flow & Error Handling

### 6.1 Endpoints
- **`GET /api/tasks`**: Filter by `status`, `assigned_agent_id`, `include_cancelled`. Protected by `require_runtime_auth`.
- **`POST /api/tasks`**: Creates task (`201 Created`), initializes `version = 1`, logs initial audit entry.
- **`GET /api/tasks/{task_id}`**: Retrieves task and audit trail. Returns `404 Not Found` if missing.
- **`PATCH /api/tasks/{task_id}`**: Partial update verifying optimistic concurrency (`version`), employee existence (`404`), and state machine rules (`409`).
- **`POST /api/tasks/{task_id}/cancel`**: Idempotent cancellation updating `cancelled_at` and `version`.

### 6.2 Error Handling Principles
- **No False Success**: If AgentHQ rejects a save (e.g. 409 version mismatch, 404 missing employee, 400 validation error), Hermes3D returns that exact HTTP status and error message to the browser.
- **Pre-check Verification Safety**: In `PUT /api/task-store`, Hermes3D verifies task existence via `GET /api/tasks/{id}`. If this check fails with `500` or a connection error, Hermes3D immediately aborts and returns an error — it **never** blindly attempts `POST /api/tasks` to create duplicate records.

---

## 7. Offline Behavior & Fallback Isolation

> [!CAUTION]
> **Production Fail-Closed Policy:**
> In production (`NODE_ENV === "production"`):
> - **Zero silent fallback** to local filesystem storage is permitted.
> - If `AGENTHQ_URL` is unconfigured, Hermes3D immediately returns `503 Service Unavailable`.
> - If AgentHQ is unreachable (e.g. network partition, process crash), Hermes3D immediately returns `502 Bad Gateway` with clear diagnostics.
> 
> **Development Fallback Policy:**
> Local fallback to `shared-store.ts` is permitted **only** in non-production environments when:
> 1. `AGENTHQ_URL` is explicitly unconfigured (isolated frontend development mode); OR
> 2. `HERMES_ALLOW_LOCAL_STORE_FALLBACK="true"` is explicitly passed in environment variables.

---

## 8. Execution Boundaries & Autonomy Guarantees

> [!IMPORTANT]
> **Strict Execution Boundaries:**
> Task management in AgentHQ is **strictly declarative project management**.
>
> Task creation, status modification, and employee assignment do **NOT**:
> 1. Trigger autonomous shell command execution.
> 2. Read or modify the host filesystem.
> 3. Simulate fake task completions with background LLM output.
> 4. Modify cloud deployments without explicit founder consent.
>
> All actual code execution remains subject to human founder approval and explicit tool sandboxing.
