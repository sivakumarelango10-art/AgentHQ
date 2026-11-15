# syntax=docker/dockerfile:1
# ==============================================================================
# AgentHQ + Hermes3D Unified Production Container
# Optimized for Render Free Tier (512 MB RAM, 0.1 CPU)
# Multi-stage build with non-root security and process supervision.
# ==============================================================================

# --- Stage 1: Build Hermes3D Frontend & Custom Server ---
FROM node:22-bookworm-slim AS node-builder
WORKDIR /build/hermes3d

# Install build toolchain for native modules (argon2, node-gyp)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    make \
    g++ \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy package manifests
COPY hermes3d/package.json hermes3d/package-lock.json ./

# Install all dependencies with dev dependencies included for building
RUN npm ci --include=dev

# Verify dependencies installed properly
RUN test -d node_modules && \
    test -f node_modules/next/package.json && \
    (test -x node_modules/.bin/next || test -f node_modules/next/dist/bin/next)

# Copy Hermes3D application source code
COPY hermes3d/ ./

# Build Next.js production bundle
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production
RUN npm run build

# Verify production output directory exists
RUN test -d .next

# --- Stage 2: Install Production Python Dependencies ---
FROM python:3.12-slim-bookworm AS python-builder
WORKDIR /build/backend

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -U pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# --- Stage 3: Unified Production Runner Image ---
FROM python:3.12-slim-bookworm AS runner

# Install runtime shared libraries: libpq for PostgreSQL, curl for healthchecks, ca-certificates for TLS
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user matching Node convention (UID 1000 / GID 1000)
RUN groupadd -g 1000 node && useradd -u 1000 -g node -s /bin/sh -m node

# Copy Node 22 binary and npm runtime from node-builder
COPY --from=node-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=node-builder /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Copy Python 3.12 virtual environment from python-builder
COPY --from=python-builder /opt/venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:/usr/local/bin:$PATH"
ENV PYTHONPATH="/app/backend"

WORKDIR /app

# Copy AgentHQ backend code and supervisor
COPY backend /app/backend
COPY docker /app/docker

# Copy Hermes3D Next.js built artifacts and server
COPY --from=node-builder /build/hermes3d/.next /app/hermes3d/.next
COPY --from=node-builder /build/hermes3d/public /app/hermes3d/public
COPY --from=node-builder /build/hermes3d/server /app/hermes3d/server
COPY --from=node-builder /build/hermes3d/node_modules /app/hermes3d/node_modules
COPY --from=node-builder /build/hermes3d/package.json /app/hermes3d/package.json
COPY --from=node-builder /build/hermes3d/next.config.ts /app/hermes3d/next.config.ts

# Concise in-builder verification of Node, Python, critical packages, and application artifacts
RUN node --version && \
    npm --version && \
    python --version && \
    python -c "import fastapi, uvicorn, sqlalchemy, psycopg, argon2" && \
    test -d /app/hermes3d/.next && \
    test -d /app/hermes3d/node_modules && \
    test -f /app/hermes3d/server/index.js && \
    test -f /app/docker/entrypoint.py

# Configure execution environment
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=10000
ENV HOST=0.0.0.0
ENV AGENTHQ_INTERNAL_URL=http://127.0.0.1:8000
ENV AGENTHQ_URL=http://127.0.0.1:8000
ENV HERMES3D_DIR=/app/hermes3d

# Ensure non-root ownership and execution
RUN chown -R node:node /app /opt/venv
USER node

# Expose public Render port
EXPOSE 10000

# Container Healthcheck targeting Hermes3D public health probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT:-10000}/api/health || exit 1

# Launch the unified process supervisor using Python 3.12 virtual environment explicitly
ENTRYPOINT ["/opt/venv/bin/python", "/app/docker/entrypoint.py"]
