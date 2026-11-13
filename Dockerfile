# syntax=docker/dockerfile:1
# Stage 1: install the receiver's Node dependencies reproducibly (npm ci, no dev-only extras beyond tsx which the bridge needs at run time).
FROM node:22-slim AS node-deps
WORKDIR /app
COPY package.json package-lock.json ./
COPY packages/sdk/package.json packages/sdk/package.json
COPY packages/mcp-server/package.json packages/mcp-server/package.json
RUN --mount=type=cache,target=/root/.npm npm ci --workspaces --include-workspace-root

# Stage 2: Python runtime with the node binary copied in for the bridge (same Debian family, so the binary is compatible).
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ORDERGUARD_HOME=/app/var/orderguard OG_RESULTS_DIR=/app/var/results OG_LLM=replay
COPY --from=node-deps /usr/local/bin/node /usr/local/bin/node
RUN useradd --create-home --uid 10001 orderguard
WORKDIR /app
COPY --from=node-deps /app/node_modules ./node_modules
COPY --chown=orderguard:orderguard . .
# Editable install on purpose: the package locates receiver/, data/ and docs relative to the repository root (see orderguard_guard.ROOT),
# so the source tree stays at /app and the console scripts point at it.
RUN pip install -e . && mkdir -p /app/paper-policy /app/var/results /app/var/replay \
    && chown -R orderguard:orderguard /app/var
USER orderguard
EXPOSE 8600
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,sys,urllib.request; token=os.getenv('ORDERGUARD_APP_TOKEN'); request=urllib.request.Request('http://127.0.0.1:8600/api/health',headers={'Authorization':'Bearer '+token} if token else {}); sys.exit(0 if urllib.request.urlopen(request, timeout=4).status == 200 else 1)"
CMD ["orderguard", "serve", "--host", "0.0.0.0", "--port", "8600"]
