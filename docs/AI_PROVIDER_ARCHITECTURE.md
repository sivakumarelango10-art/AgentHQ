# AgentHQ AI Provider Architecture

**Status:** Production Ready  
**Version:** 1.0 (Phase 2B)  
**Layer:** Core Intelligence & Cloud Inference Dispatch  
**Supported Providers:** Ollama (Local Development) & Cloudflare Workers AI (Cloud Production)  

---

## 1. Provider Abstraction Overview

AgentHQ provides an extensible, decoupled AI provider abstraction allowing the company runtime to execute on local hardware via Ollama or in zero-cost cloud environments via Cloudflare Workers AI:

```mermaid
flowchart TD
    UserChat[Founder Chat / Hermes3D 3D Office] --> APIRoute[FastAPI Chat Dispatcher\nbackend/app/main.py]
    
    APIRoute --> ProviderFactory[get_ai_provider()\nAI_PROVIDER env switch]
    
    ProviderFactory -->|AI_PROVIDER=ollama| OllamaProv[OllamaProvider\nqwen3:4b\nhttp://127.0.0.1:11434/api/chat]
    ProviderFactory -->|AI_PROVIDER=cloudflare| CFProv[CloudflareWorkersAIProvider\n@cf/qwen/qwen3.8-27b\nOpenAI-Compatible REST Endpoint]
    
    CFProv --> QuotaGuard{Daily Quota Guard\nreserve_ai_quota()\nCeiling: 8,500 Neurons}
    QuotaGuard -->|Usage >= 8,500| Reject[HTTP 429 Too Many Requests\nRetry-After: seconds to 00:00 UTC]
    QuotaGuard -->|Usage < 8,500| Dispatch[Cloudflare Workers AI Endpoint\nPOST /ai/v1/chat/completions]
    
    Dispatch --> Reconcile[reconcile_ai_quota()\nAdjust with actual token usage]
    Reconcile --> Sanitizer[Response Sanitizer\nStrip <think> & internal monologue]
    Sanitizer -->|Clean Answer| StoreDB[(PostgreSQL / SQLite Persistence\nconversation_messages)]
    Sanitizer -->|Monologue Detected| Retry[Bounded Single Retry\nStrict Final Answer Instruction\nAdditional Quota Reserved]
    Retry --> StoreDB
```

---

## 2. Supported Providers & Model Configurations

| Attribute | Local Ollama Provider | Cloudflare Workers AI Provider |
| :--- | :--- | :--- |
| **Provider Name** | `ollama` | `cloudflare` |
| **Default Model** | `qwen3:4b` | `@cf/qwen/qwen3.8-27b` |
| **Endpoint Format** | Ollama Native (`/api/chat`) | OpenAI-compatible (`/ai/v1/chat/completions`) |
| **Authentication** | Local loopback (no auth required) | HTTP Header `Authorization: Bearer <CLOUDFLARE_API_TOKEN>` |
| **Environment Toggle** | `AI_PROVIDER=ollama` | `AI_PROVIDER=cloudflare` |
| **Cost** | 100% Free (Local GPU/CPU) | 100% Free Tier (10,000 neurons/day) |
| **Reasoning Mode** | Toggle via `OLLAMA_THINK=true/false` | Direct user-facing final output |

---

## 3. Daily AI Quota & Neuron Accounting

Cloudflare allocates **10,000 Neurons per day** on its free tier, resetting automatically at **00:00 UTC**.

To ensure AgentHQ never exceeds the free tier or encounters unexpected provider rejection, an authoritative quota guard is implemented in the database layer (`daily_ai_usage` table):

### 3.1 Model-Specific Neuron Formula
Published Cloudflare Workers AI consumption rates for Qwen 27B class models:
* **Input Rate:** 40,909 neurons per 1,000,000 tokens ($0.040909$ neurons/token).
* **Output Rate:** 290,909 neurons per 1,000,000 tokens ($0.290909$ neurons/token).

$$\text{Estimated Neurons} = \left(\text{Input Tokens} \times \frac{40,909}{1,000,000}\right) + \left(\text{Output Tokens} \times \frac{290,909}{1,000,000}\right)$$

### 3.2 Two-Phase Quota Lifecycle
1. **Atomic Pre-Dispatch Reservation (`reserve_ai_quota`):**
   * Before dispatching an inference call, the input tokens are estimated from prompt messages and added to the max output tokens budget (700 tokens).
   * If today's cumulative neurons plus the provisional reservation exceeds the safety ceiling of **8,500 Neurons**, the request is rejected immediately with HTTP 429.
2. **Post-Dispatch Reconciliation (`reconcile_ai_quota`):**
   * When Cloudflare responds with `usage.prompt_tokens` and `usage.completion_tokens`, the provisional reservation is adjusted to reflect exact consumption.
3. **Failure Policy:**
   * If an error occurs *before* network dispatch (e.g., local validation error), the provisional quota is released via `release_ai_quota`.
   * If a timeout occurs *during* inference, the reservation is retained to ensure uncertain or slow remote execution cannot cause quota overruns.
4. **Zero Paid Fallback:**
   * When quota is exhausted or Cloudflare is unavailable, AgentHQ fails gracefully with HTTP 429 or HTTP 502. It **never** silently redirects requests to paid third-party APIs.

---

## 4. Response Sanitization & Controlled Retry

To protect company communication quality and avoid exposing model reasoning traces to the Founder or Hermes3D 3D canvas:
1. **Think Tag Excision:** Any `<think>...</think>` reasoning block is cleanly removed from the response.
2. **Drafting Narration Filtering:** Responses beginning with scratchpad phrases (*"Okay, the user wants me to..."*, *"Mental note:"*, *"Let me reason through..."*) are rejected.
3. **Single Bounded Retry:**
   * If a raw completion is rejected by the sanitizer, exactly one retry is executed with a reinforced system instruction:  
     `"FINAL RESPONSE REQUIREMENT: Return only the final answer for the Founder. Do not output analysis, self-talk, scratchpad, planning notes, or think tags."`
   * The retry attempt is tracked against the daily neuron quota.
   * If the retry also fails to produce clean prose, the turn is aborted with HTTP 502 without storing or exposing draft text.

---

## 5. Security & Isolation Boundary
* **No Frontend Exposure:** Cloudflare credentials (`CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`) reside strictly in server-side environment variables and are never transmitted to Hermes3D or the client browser.
* **Redacted Error Reporting:** HTTP 401 or 403 errors from Cloudflare are returned as generic HTTP 502 messages (*"Cloudflare Workers AI authentication failed. Please verify credentials."*) without leaking token fragments.

