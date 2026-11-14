# Phase 3.1.1: Docker Build Context and Repository Audit

**Role:** Principal DevOps Architect  
**Audit Date:** 2026-11-14  
**Repositories Examined:** `E:\AgentHQ` and `E:\Hermes3D`  
**Active Branch:** `feature/cloud-readiness`  
**Status:** COMPLETE (READ-ONLY AUDIT)  

---

## 1. Executive Summary

This read-only audit evaluates the Docker build context and repository integration between **AgentHQ** and **Hermes3D** for deployment on **Render Free**.

### Critical Findings
1. **Build Context Isolation:** `AgentHQ` and `Hermes3D` are completely independent Git repositories with distinct origins:
   - `AgentHQ`: `https://github.com/sivakumarelango10-art/AgentHQ.git`
   - `Hermes3D`: `https://github.com/iamlukethedev/Hermes3D.git`
2. **Missing Source in Build Context:** The current `AgentHQ/Dockerfile` attempts to build Hermes3D during Stage 1 (`node-builder`) using `COPY package*.json ./` and `COPY . ./`. However, the `AgentHQ` repository contains **zero Hermes3D source files**. There is no root `package.json` in `AgentHQ` (only a legacy Vite `frontend/package.json`).
3. **Render Build Failure Risk:** When Render builds a Web Service from `sivakumarelango10-art/AgentHQ`, its Docker context (`dockerContext: .`) only contains the cloned `AgentHQ` repository. Under the current configuration, any build on Render will fail immediately at Docker Stage 1 because Next.js source code, assets, and configs are absent.
4. **Local Commit Asymmetry:** In `E:\Hermes3D`, branch `feature/cloud-readiness` contains local commits (`4d10243` and `6b18315`) authored by `sivakumarelango10-art` that **do not exist on the upstream remote** (`iamlukethedev/Hermes3D.git`). Furthermore, the remote repository `https://github.com/sivakumarelango10-art/Hermes3D.git` does not yet exist.

---

## 2. Dockerfile & Build Context Inspection

### 2.1 Inspection of `E:\AgentHQ\Dockerfile`

| Stage | Line Range | Instruction | Audit Analysis & Status |
| :--- | :--- | :--- | :--- |
| **Stage 1 (`node-builder`)** | [Lines 10-13](file:///E:/AgentHQ/Dockerfile#L10-L13) | `WORKDIR /build/hermes3d`<br>`COPY package*.json ./` | **FAIL (Missing Target):** Assumes `package.json` is at the root of the build context. In `AgentHQ`, root `package.json` does not exist (`Test-Path E:\AgentHQ\package.json` returns `False`). |
| **Stage 1 (`node-builder`)** | [Lines 17-20](file:///E:/AgentHQ/Dockerfile#L17-L20) | `COPY . ./`<br>`RUN if [ -f package.json ]; then npm run build; fi` | **FAIL (Missing Code):** Copies AgentHQ root files (backend, docs) instead of Hermes3D source files. `npm run build` is skipped or fails. |
| **Stage 2 (`python-builder`)** | [Lines 34-36](file:///E:/AgentHQ/Dockerfile#L34-L36) | `COPY backend/requirements.txt ./`<br>`RUN pip install ...` | **PASS:** `AgentHQ/backend/requirements.txt` exists and resolves properly within context. |
| **Stage 3 (`runner`)** | [Lines 58-59](file:///E:/AgentHQ/Dockerfile#L58-L59) | `COPY backend /app/backend`<br>`COPY docker /app/docker` | **PASS:** `AgentHQ/backend` and `AgentHQ/docker` exist and resolve properly within context. |
| **Stage 3 (`runner`)** | [Lines 62-67](file:///E:/AgentHQ/Dockerfile#L62-L67) | `COPY --from=node-builder /build/hermes3d/.next ...`<br>`COPY --from=node-builder /build/hermes3d/server ...` | **FAIL (Missing Artifacts):** Because Stage 1 has no Hermes3D source, `/build/hermes3d/.next` and `/build/hermes3d/server` do not exist in `node-builder`, causing Docker build to abort. |

### 2.2 Inspection of `E:\AgentHQ\.dockerignore`
[Lines 1-24](file:///E:/AgentHQ/.dockerignore#L1-L24):
- Properly excludes `.git`, `**/.env*`, `backend/.venv/`, and `*.db`.
- Does **not** ignore potential submodule directories such as `hermes3d/`. If `hermes3d` is checked out as a submodule or directory, it will pass through to the Docker daemon.

### 2.3 Inspection of `E:\AgentHQ\render.yaml`
[Lines 14-15](file:///E:/AgentHQ/render.yaml#L14-L15):
```yaml
dockerfilePath: ./Dockerfile
dockerContext: .
```
Render checks out the root of `AgentHQ` and uses `.` as the build context. Without an explicit repository linkage, Render cannot see sibling folder `E:\Hermes3D`.

---

## 3. Required Paths for Building Hermes3D

To successfully compile the Next.js production standalone server in Docker Stage 1, the following paths from `Hermes3D` must be present in the build context:

1. `package.json` & `package-lock.json` (Dependencies)
2. `next.config.ts` (Next.js compilation settings)
3. `tsconfig.json` & `next-env.d.ts` (TypeScript environment)
4. `postcss.config.mjs` (Tailwind CSS v4 compilation)
5. `src/` (Application routes, components, 3D office hooks, stores, and API routes)
6. `public/` (3D models, textures, sounds, office layout metadata)
7. `server/` (Custom production server: `index.js`, `access-gate.js`, `gateway-proxy.js`, `network-policy.js`)

**Current Location:** All 7 required paths exist exclusively in `E:\Hermes3D` and are absent from `E:\AgentHQ`.

---

## 4. Architectural Approaches Evaluation

We evaluate three strategies for bringing Hermes3D into AgentHQ's Docker build context:

| Evaluation Criteria | Approach A: Git Submodule (Recommended) | Approach B: Git Subtree | Approach C: Monorepo Migration |
| :--- | :--- | :--- | :--- |
| **Repository Independence** | **High:** Both repos maintain independent Git histories and remotes. | **Medium:** Merges Hermes3D commits into AgentHQ commit log. | **None:** Merges both projects permanently into a single repo. |
| **Render Compatibility** | **High:** Render natively runs `git submodule update --init --recursive`. | **High:** Files are natively in the repository tree. | **High:** All files natively in single repo. |
| **Reproducibility** | **Exact:** Parent repo pins an exact, immutable commit SHA (gitlink). | **Exact:** Files tracked directly in tree. | **Exact:** Files tracked directly in tree. |
| **Code Duplication** | **Zero:** No duplicated files in version control. | **High:** Full duplication of all source files in Git objects. | **Zero:** Files live in a single unified repository. |
| **Developer Workflow** | Requires submodule commands (`--recurse-submodules`). | Requires `git subtree pull/push` commands. | Standard single-repo workflow. |
| **Prerequisites** | Requires a remote fork of Hermes3D with pushed commits. | No remote fork strictly required to commit. | Destructive repository merge. |

---

## 5. Detailed Analysis of Approach A: Git Submodule

### 5.1 Public / Private Repository Accessibility
- **Render Submodule Support:** Render's build agent executes:
  ```bash
  git submodule update --init --recursive
  ```
- **HTTPS vs SSH:** Submodules configured via HTTPS (`https://github.com/<owner>/<repo>.git`) can be cloned by Render without SSH key setup if the repository is public.
- **Private Submodule Constraint:** If the Hermes3D fork is private, Render requires a Personal Access Token (PAT) with `repo` scope or an authorized GitHub organization connection.

### 5.2 Pinned Hermes3D Commit & Remote Fork Requirement
In `E:\Hermes3D`, the current commit on `feature/cloud-readiness` is:
- **Commit SHA:** `6b18315e5d196ad2a1e72aac2cd0c4e4ec5b318e`
- **Author:** `sivakumarelango10-art <sivakumarelango10@gmail.com>`
- **Upstream Origin:** `https://github.com/iamlukethedev/Hermes3D.git`

**Critical Finding:**  
`sivakumarelango10-art` does not have push permissions to upstream `iamlukethedev/Hermes3D.git`. If a submodule is added pointing to `https://github.com/iamlukethedev/Hermes3D.git`, Render will attempt to check out commit `6b18315` from upstream and **fail with `fatal: reference is not a tree`**, because commit `6b18315` only exists locally.

**Required Action for Submodule Implementation:**
1. Create a remote fork or repository on GitHub: `https://github.com/sivakumarelango10-art/Hermes3D.git`.
2. Push branch `feature/cloud-readiness` to that remote repository.
3. In `AgentHQ`, add the submodule pointing to `https://github.com/sivakumarelango10-art/Hermes3D.git` at path `hermes3d`.

### 5.3 Docker Context Alignment
Once `hermes3d` is checked out as a submodule inside `AgentHQ`:
The directory tree inside `AgentHQ` becomes:
```
E:\AgentHQ
├── backend/
├── docker/
├── docs/
├── hermes3d/             <-- Git Submodule (pinned to commit 6b18315)
│   ├── package.json
│   ├── next.config.ts
│   ├── server/
│   ├── src/
│   └── public/
├── Dockerfile
├── render.yaml
└── .dockerignore
```

The Dockerfile Stage 1 then cleanly references the submodule:
```dockerfile
# --- Stage 1: Build Hermes3D Frontend ---
FROM node:22-bookworm-slim AS node-builder
WORKDIR /build/hermes3d

COPY hermes3d/package.json hermes3d/package-lock.json ./
RUN npm ci --ignore-scripts

COPY hermes3d/ ./
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production
RUN npm run build
```

---

## 6. Audit Conclusion & Next Steps

1. **Current State:** The Docker build context in `E:\AgentHQ` is **incomplete** because Hermes3D source code is absent from the repository. Builds dispatched to Render under the current configuration will fail.
2. **Recommended Resolution:** **Approach A (Git Submodule)** is the optimal architectural pattern. It preserves independent repository boundaries, eliminates code duplication, and provides deterministic, reproducible builds on Render.
3. **Execution Roadmap (Post-Audit):**
   - **Step 1:** Create remote fork `sivakumarelango10-art/Hermes3D` on GitHub.
   - **Step 2:** Push `feature/cloud-readiness` from `E:\Hermes3D` to the remote fork.
   - **Step 3:** Add submodule in `AgentHQ`:
     `git submodule add https://github.com/sivakumarelango10-art/Hermes3D.git hermes3d`
   - **Step 4:** Update `AgentHQ/Dockerfile` to copy from `hermes3d/`.
   - **Step 5:** Update `docker/entrypoint.py` to point `self.hermes_dir` to `/app/hermes3d`.

*Audit completed with zero file modifications, zero dependency installations, and zero commits or pushes.*

