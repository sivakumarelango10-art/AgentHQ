# Cloudflare Workers AI Setup Guide

**Document Version:** 1.0 (Phase 2B)  
**Target Model:** `@cf/qwen/qwen3.8-27b`  
**Endpoint:** OpenAI-Compatible REST API (`/ai/v1/chat/completions`)  

---

## 1. Overview

AgentHQ uses **Cloudflare Workers AI** to deliver high-performance, 27-billion parameter AI employee interactions on Cloudflare's global edge network under their **100% free tier allocation** (10,000 neurons/day).

---

## 2. Generating Cloudflare Credentials

### Step 1: Locate Your Cloudflare Account ID
1. Log in to the [Cloudflare Dashboard](https://dash.cloudflare.com/).
2. In the navigation sidebar, navigate to **Compute (Workers) > Workers & Pages** (or select any domain).
3. On the right-hand sidebar under **Account Details**, copy your **Account ID** (a 32-character hexadecimal string).

### Step 2: Create a Workers AI API Token
1. In the top right corner of the dashboard, click your **User Profile** icon and select **My Profile**.
2. Select **API Tokens** from the left navigation menu.
3. Click **Create Token**.
4. Choose the **Workers AI (Read/Edit)** template (or create a Custom Token with the permission:  
   `Account` > `Workers AI` > `Edit`).
5. Set the Account Resources to include your target Cloudflare account.
6. Click **Continue to summary** and then **Create Token**.
7. **Copy and securely store your API token immediately** (it will only be displayed once).

---

## 3. Configuring AgentHQ

Set the following environment variables in your server environment (or local `backend/.env` for testing):

```bash
# Select Cloudflare as active provider
AI_PROVIDER=cloudflare

# Cloudflare Credentials (Backend server only - NEVER expose to frontend)
CLOUDFLARE_ACCOUNT_ID=your_account_id_here
CLOUDFLARE_API_TOKEN=your_api_token_here
CLOUDFLARE_MODEL=@cf/qwen/qwen3.8-27b

# Conservative Daily Neuron Safety Limit (Default: 8500 out of 10000 free neurons)
CLOUDFLARE_DAILY_NEURON_LIMIT=8500
```

---

## 4. Verifying Provider Connectivity

### 4.1 Health Check Endpoint
Query the AgentHQ health endpoint to confirm provider readiness:

```bash
curl http://127.0.0.1:8000/api/health
```

Expected response when connected:
```json
{
  "status": "ok",
  "app": "AgentHQ API",
  "database": "connected",
  "database_mode": "sqlite",
  "provider": "cloudflare",
  "ollama_connected": false,
  "model": "@cf/qwen/qwen3.8-27b"
}
```

### 4.2 Inspecting Daily Neuron Quota
AgentHQ provides a dedicated endpoint to observe your daily free tier neuron consumption:

```bash
curl http://127.0.0.1:8000/api/ai/quota
```

Sample output:
```json
{
  "provider": "cloudflare",
  "usage_date": "2026-11-14",
  "daily_limit_neurons": 8500.0,
  "current_neurons": 186.3635,
  "remaining_neurons": 8313.6365,
  "is_exhausted": false,
  "reset_at": "2026-11-15T00:00:00+00:00",
  "retry_after_seconds": 48920
}
```

---

## 5. Free-Tier Quota & Daily Reset Mechanics
* **Daily Free Budget:** 10,000 Neurons per calendar day.
* **AgentHQ Safety Ceiling:** 8,500 Neurons per day (guarantees a 15% safety buffer to prevent hard provider lockouts).
* **Reset Schedule:** The neuron counter automatically resets at **00:00 UTC** daily.
* **Quota Exhaustion Behavior:** When usage reaches 8,500 neurons, AgentHQ responds with HTTP 429 Too Many Requests containing a `Retry-After` header specifying the exact seconds until midnight UTC.

