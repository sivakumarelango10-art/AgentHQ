# Founder Authentication Guide

## 1. Overview

AgentHQ adheres to a single-owner model for company administration and autonomous fleet coordination. There is no public user registration.

Access to the system is protected by:
1. Configurable owner username (`STUDIO_USERNAME` or `OWNER_USERNAME`, default: `founder`).
2. Configurable password hash (`STUDIO_PASSWORD_HASH` or `OWNER_PASSWORD_HASH`).
3. Argon2id password hashing algorithm.
4. Cryptographically signed, revocable HTTP sessions (`studio_session`).
5. In-memory IP rate limiting (lockout on repeated failures).

---

## 2. Generating the Argon2id Password Hash

Passwords must NEVER be stored in plaintext. Generate an Argon2id hash prior to deployment and set it in your environment configuration.

### Using Node.js (Hermes3D directory)
```bash
cd E:\Hermes3D
node -e "const argon2 = require('argon2'); argon2.hash('YourStrongPasswordHere!').then(console.log);"
```

### Using Python (AgentHQ directory)
```bash
cd E:\AgentHQ\backend
.\.venv\Scripts\python -c "import argon2; ph = argon2.PasswordHasher(); print(ph.hash('YourStrongPasswordHere!'))"
```

Output format example:
```
$argon2id$v=19$m=65536,t=3,p=4$PxmKn2z2/ABJBjqXnCYAuw$TQbJY45d+Aaa11+bXTnOLJTu+aO3FfX3cB0w4F1NDSQ
```

Copy the entire output string and assign it to `STUDIO_PASSWORD_HASH` in `.env`.

---

## 3. Environment Configuration

### Backend (`E:\AgentHQ\backend\.env`)
```ini
ENVIRONMENT=production
STUDIO_USERNAME=founder
STUDIO_PASSWORD_HASH=$argon2id$v=19$m=65536,t=3,p=4$...
SESSION_SECRET=a_random_32_plus_character_string_for_signing_sessions_and_tickets
RUNTIME_API_TOKEN=strong_random_token_for_machine_to_machine_calls
CORS_ORIGINS=https://agenthq.onrender.com,https://your-custom-domain.com
```

### Hermes3D (`E:\Hermes3D\.env`)
```ini
NODE_ENV=production
STUDIO_USERNAME=founder
STUDIO_PASSWORD_HASH=$argon2id$v=19$m=65536,t=3,p=4$...
SESSION_SECRET=a_random_32_plus_character_string_for_signing_sessions_and_tickets
RUNTIME_API_TOKEN=strong_random_token_for_machine_to_machine_calls
CUSTOM_RUNTIME_ALLOWLIST=agenthq-runtime.onrender.com,localhost,127.0.0.1
```

> [!IMPORTANT]
> `SESSION_SECRET` must be identical across both Hermes3D and AgentHQ if cookies or tickets are shared directly. It must be at least 32 characters long.

---

## 4. Authentication Flow

```mermaid
sequenceDiagram
    autonumber
    actor Founder as Founder (Browser)
    participant Gate as Hermes3D Access Gate
    participant AgentHQ as AgentHQ Auth API

    Founder->>Gate: GET /office (Unauthenticated)
    Gate-->>Founder: 302 Redirect to /login
    Founder->>Gate: GET /login
    Gate-->>Founder: 200 OK (Clean Dark-Themed Login UI)

    Founder->>Gate: POST /api/auth/login { username, password }
    Note over Gate: Rate limit check (Max 5 attempts / 60s)
    Note over Gate: Argon2id verification
    alt Verification Succeeded
        Note over Gate: Create signed studio_session
        Gate-->>Founder: 200 OK (Set-Cookie: studio_session; HttpOnly; SameSite=Lax; Secure)
        Founder->>Gate: GET /office with Cookie
        Gate-->>Founder: 200 OK (3D Office Canvas Loaded)
    else Verification Failed
        Note over Gate: Record IP failure count
        Gate-->>Founder: 401 Unauthorized { error: "Invalid credentials" }
    end
```

---

## 5. Rate Limiting Rules

1. **Attempt Window**: 60 seconds rolling window per client IP.
2. **Threshold**: 5 failed login attempts.
3. **Response**: HTTP 429 Too Many Requests.
4. **Header**: `Retry-After: <seconds_remaining>`.
5. **Reset**: A single successful login resets the failure counter immediately.

---

## 6. Logout and Session Invalidation

When the Founder logs out:
1. The browser sends `POST /api/auth/logout`.
2. The server extracts the `session_id` from the signed token.
3. The `session_id` is appended to the server's in-memory revocation list.
4. The server clears the `studio_session` cookie by returning `Max-Age=0` and `Expires=Thu, 01 Jan 1970 00:00:00 GMT`.
5. Any subsequent attempt to present the revoked token will be rejected with HTTP 401.

