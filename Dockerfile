# Mnemosyne MCP Server: build-from-source image for dariokan82/mnemosyne
#
# Builds the wheel from this fork (upstream mnemosyne-oss/mnemosyne v4.0.0b3
# plus the fork's deploy changes) instead of the floating PyPI package.
# Target host: lucciola (Debian 13, x86_64), where mnemosyne moves off Trevor
# (decided 2026-09-25). Also still fine on Trevor's 3.10 kernel: the base is
# glibc 2.41, outside the 2.39 danger band.
#
# Extras: embeddings (fastembed + sqlite-vec: semantic recall; a bare install
# silently degrades to keyword-only FTS5, which is not acceptable here), mcp,
# sync. NOT the local-LLM extras: ctransformers / llama-cpp-python were never
# used (MNEMOSYNE_LLM_ENABLED=false on the server; the sleep service
# summarises via the Anthropic API) and compiling llama-cpp-python cost
# 30-60 min per build on Trevor. Dropped 2026-09-25 per D's 2026-09-16 call.
# local_llm.py already degrades to None when the backend cannot import.
#
# Build:   docker build -t mnemosyne-mcp .
# Run:     see deploy/ for the compose files (SSE on 8181 behind the tunnel).

FROM python:3.11-slim AS builder

WORKDIR /build
COPY . .
RUN pip install --no-cache-dir build && python -m build --wheel

FROM python:3.11-slim

LABEL org.opencontainers.image.title="Mnemosyne MCP Server (fork build)"
LABEL org.opencontainers.image.description="Universal memory layer MCP server, built from source with embeddings + mcp extras"
LABEL org.opencontainers.image.source="https://github.com/dariokan82/mnemosyne"
LABEL org.opencontainers.image.licenses="MIT"

# gosu: entrypoint.sh reconciles uid/gid to PUID/PGID at start, then drops
# root. uid/gid 1000 below is a placeholder it rewrites.
RUN apt-get update && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin mnemosyne

COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir "$(ls /tmp/*.whl)[embeddings,mcp,sync]" "anthropic>=0.40" \
    && rm -rf /tmp/*.whl

# MNEMOSYNE_DATA_DIR only governs the sqlite db; the fastembed ONNX cache
# lives under ~/.hermes. HOME inside the volume keeps it across recreates.
ENV MNEMOSYNE_DATA_DIR=/data
ENV HOME=/data/home
VOLUME /data

# claude_sleep.py lives under deploy/synology/ because .dockerignore excludes
# scripts/ from the build context.
COPY deploy/synology/claude_sleep.py /usr/local/bin/claude_sleep.py
COPY deploy/synology/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Is the server listening? Nothing more: upstream's probe cold-loads the
# embedding model and could never finish inside its timeout (2026-09-16).
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
    CMD python -c "import socket; socket.create_connection((\"127.0.0.1\", 8181), 3).close()" || exit 1

# Root until entrypoint.sh drops to the mnemosyne user via gosu.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD []
