# AgentHQ Runtime API Authentication

## 1. Overview

AgentHQ's FastAPI runtime serves as the authoritative backend for:
- AI Employee state and directory (`/api/agents`).
- Work item scheduling and execution (`/api/tasks`).
- Conversational threads and message history (`/api/conversations`).
- Autonomous model dispatch (`/v1/chat/completions`, `/api/agents/{id}/chat`).
- Daily AI token quota enforcement (`/api/ai/quota`).

In cloud deployments, AgentHQ is protected by **Bearer Token Authentication** using the `RUNTIME_API_TOKEN` environment variable.

---

## 2. Machine-to-Machine Authentication Model

The browser client interacts exclusively with Hermes3D using ambient `studio_session` cookies.

When Hermes3D needs to communicate with AgentHQ:
1. The Next.js custom runtime route (`/api/runtime/custom`) intercepts the browser call.
2. Hermes3D validates the browser's session.
3. Hermes3D injects `Authorization: Bearer <RUNTIME_API_TOKEN>` into the upstream request to AgentHQ.
4. AgentHQ validates the Bearer token in constant time.
5. AgentHQ executes the request and returns the result to Hermes3D.
6. Hermes3D streams or forwards the sanitized response to the browser.

```
+---------+         Session Cookie         +-----------+      Bearer Token      +---------+
| Browser | -----------------------------> | Hermes3D  | ---------------------> | AgentHQ |
| Client  | <----------------------------- | Server    | <--------------------- | Runtime |
+---------+          Clean JSON            +-----------+      Clean Response    +---------+
                         (No API Tokens)                       (RUNTIME_API_TOKEN)
```

---

## 3. Endpoints and Access Control

### 3.1 Public Endpoints (Exempt from Auth)
The following endpoints must be accessible without credentials for hosting platforms (Render, health checks, uptime monitors):
- `GET /health` (Hermes3D runtime health probe)
- `GET /api/health` (AgentHQ subsystem health probe)
- `GET /` (Service root ping)

### 3.2 Protected Runtime Endpoints (Require Bearer Token or Founder Session)
- `GET /api/agents`
- `POST /api/agents` (Requires Founder role)
- `GET /api/tasks`
- `POST /api/tasks` (Requires Founder role)
- `PATCH /api/tasks/{task_id}/cancel` (Requires Founder role)
- `GET /api/conversations`
- `GET /api/conversations/{id}/messages`
- `POST /api/agents/{agent_id}/chat`
- `POST /v1/chat/completions`
- `GET /api/ai/quota` (Requires Founder role)
- `GET /state`
- `GET /registry`
- `GET /api/ollama/status`

---

## 4. Constant-Time Verification

To eliminate timing attacks, the token comparison uses Python's `secrets.compare_digest`:

```python
import secrets

def require_runtime_auth(request: Request) -> dict[str, Any]:
    auth_header = request.headers.get("Authorization", "").strip()
    configured_token = get_runtime_api_token()

    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):].strip()
        if configured_token and token and secrets.compare_digest(token, configured_token):
            return {"authenticated": True, "auth_type": "bearer", "role": "runtime"}

    # Fallback to session cookie if called directly by browser
    session = get_current_session(request)
    if session is not None:
        return {"authenticated": True, "auth_type": "cookie", "role": session.get("role", "founder")}

    raise HTTPException(status_code=401, detail="Authentication required. Provide valid Bearer token.")
```

---

## 5. Enforcement Behavior

- **Production Mode (`ENVIRONMENT=production`)**:
  Authentication is **strictly mandatory**. Requests missing `Authorization: Bearer <token>` or a valid session cookie will be rejected with `HTTP 401 Unauthorized` and header `WWW-Authenticate: Bearer`.
- **Configured Mode (`RUNTIME_API_TOKEN` is non-empty)**:
  Authentication is **strictly mandatory**.
- **Local Dev Permissive Mode (`RUNTIME_API_TOKEN` is unset & `ENVIRONMENT != production`)**:
  For rapid offline development, endpoints run in permissive mode unless `AUTH_ENFORCED=true` is set.

