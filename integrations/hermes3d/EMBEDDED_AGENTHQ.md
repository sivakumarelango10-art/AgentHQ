# Hermes3D embedded in AgentHQ

## User experience
Hermes3D appears inside AgentHQ under the **Live Office** navigation item. The browser remains on the AgentHQ Vite origin (`http://127.0.0.1:5173`); the embedded `/office` page and its Next.js assets/API routes are reverse-proxied by Vite to the local Hermes3D service on port 3000.

This is an in-app integration, not a direct copy of Hermes3D source into the Vite bundle and not a cross-origin iframe. Hermes3D retains its own local Next.js process because its OfficeScreen is a large, tightly coupled Studio feature. AgentHQ remains the product shell and the only browser workspace.

## Local services
| Service | URL / port |
|---|---|
| AgentHQ FastAPI + SQLite + Ollama adapter | `http://127.0.0.1:8000` |
| AgentHQ Vite shell | `http://127.0.0.1:5173` |
| Hermes3D Next.js Studio (background service) | `http://127.0.0.1:3000` |
| Ollama | `http://127.0.0.1:11434` |

## How the embedding works
- The AgentHQ `Live Office` view renders an iframe with `src="/office"`.
- Vite proxies `/office`, `/_next`, `/api`, `/office-assets`, and `/spotify` to `http://127.0.0.1:3000`.
- Because the browser sees the iframe as the same origin (`127.0.0.1:5173`), Hermes3D keeps its existing `frame-ancestors 'self'` and `X-Frame-Options: SAMEORIGIN` protections. No weakening of Hermes3D CSP is needed.
- `/api` is routed to Hermes3D because AgentHQ frontend API helpers call FastAPI explicitly at `127.0.0.1:8000`; these route namespaces do not collide.
- `ws: true` supports Next.js dev HMR and Hermes3D gateway WebSocket upgrades through the proxy.
- `/office-assets` serves Hermes3D models, HDR environment and office assets.

## Start-up on Windows
Start and keep these three terminal services running:

### Terminal 1 — AgentHQ backend
```powershell
cd E:\AgentHQ\backend
Set-ExecutionPolicy -Scope Process Bypass -Force
.\run.ps1
```

### Terminal 2 — Hermes3D background service
```powershell
cd E:\Hermes3D
npm run dev
```

### Terminal 3 — AgentHQ workspace
```powershell
cd E:\AgentHQ\frontend
npm run dev
```

Open only `http://127.0.0.1:5173`. Click **Live Office** in the AgentHQ sidebar. You do not need a separate browser tab for port 3000, and you do not need to run the Hermes3D demo gateway.

## First-time connection after embedding
The first time Hermes3D opens inside AgentHQ, it may show the connection wizard again. Browser storage is origin-scoped: the old settings were saved under `localhost:3000`, while the embedded view now uses `127.0.0.1:5173`.

Choose **Custom backend**, set the upstream URL to `http://127.0.0.1:8000`, leave the token empty for this local single-machine setup, then connect. Verify the AgentHQ employee roster and `qwen3:4b` model. This creates settings for the embedded origin and does not delete your old Hermes3D settings.

## Troubleshooting
- If the iframe is blank or displays a connection error, ensure Hermes3D is running on port 3000, then restart the AgentHQ Vite server so it reloads `vite.config.ts`.
- If Vite reports a proxy error, check that `http://127.0.0.1:3000/office` opens directly in a temporary tab.
- If the embedded office shows the setup wizard, configure Custom backend once for the embedded origin as described above.
- Use the **Open full screen** link only when you deliberately want the office without the AgentHQ shell; it still uses AgentHQ origin and proxy.
- Do not remove Hermes3D CSP or X-Frame-Options headers. The same-origin proxy is intentional so those protections remain active.

## Production note
This Vite proxy is configured for the local development workflow used by AgentHQ. A production deployment needs an equivalent reverse-proxy configuration routing Hermes3D paths to the private local/server-side Hermes3D service. Do not expose the unauthenticated local AgentHQ development API or Hermes3D service directly to a public network.

## Future direction
The long-term option is to extract smaller, reusable Hermes3D renderer modules into AgentHQ's own React Three Fiber application. The current Hermes3D `OfficeScreen` and `RetroOffice3D` are tightly coupled to many Studio stores, screens, APIs and layout systems; copying them wholesale into the Vite bundle would create a fragile, duplicated application shell. The same-origin embedded view gives AgentHQ one coherent workspace now while preserving the option for a careful renderer migration later.