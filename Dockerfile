# Mnemosyne MCP Server — hardened, build-from-source image for Trevor (Synology)
#
# Builds the wheel from this fork's pinned source (v3.14.0,
# mnemosyne-oss/mnemosyne @ 4e5ed14) instead of `pip install mnemosyne-memory`
# from the floating PyPI package, and installs the [all] extra -- fastembed
# (semantic recall) and ctransformers/llama-cpp-python (local LLM
# consolidation) are required. A bare install silently degrades to
# keyword-only FTS5 retrieval with no warning, which is explicitly not
# acceptable here.
#
# Build:
#   docker build -t mnemosyne-mcp:v3.14.0 .
#
# Run: see docker-compose.yml -- SSE transport, same pattern as the
# mnemo-mcp / port-mcp stacks already on Trevor. The Cloudflare tunnel
# (already running as its own stack) is what actually exposes this to the
# internet; this container just publishes the port like its siblings do.

FROM python:3.11-slim AS builder

WORKDIR /build
COPY . .
RUN pip install --no-cache-dir build && python -m build --wheel

FROM python:3.11-slim

LABEL org.opencontainers.image.title="Mnemosyne MCP Server (hardened fork build)"
LABEL org.opencontainers.image.description="Universal memory layer MCP server for any AI agent — built from source, [all] extras, pinned to v3.14.0"
LABEL org.opencontainers.image.source="https://github.com/dariokan82/mnemosyne"
LABEL org.opencontainers.image.licenses="MIT"

# gosu: drop root cleanly after the entrypoint reconciles uid/gid at
# container start (see entrypoint.sh). build-essential/cmake/git:
# llama-cpp-python may need to compile from source if no prebuilt wheel
# matches this platform; purged after the pip install below.
RUN apt-get update && apt-get install -y --no-install-recommends \
      gosu build-essential cmake git \
    && rm -rf /var/lib/apt/lists/*

# uid/gid 1000 here is just a placeholder -- entrypoint.sh rewrites both
# to PUID/PGID at container start (default: same setup as the
# linuxserver.io syncthing/plex images already on Trevor), so the bind
# mount ends up owned by whichever Synology account you point it at
# instead of a hardcoded guess.
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin mnemosyne

COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir "$(ls /tmp/*.whl)[all]" && rm -rf /tmp/*.whl \
    && apt-get purge -y --auto-remove build-essential cmake git

# MNEMOSYNE_DATA_DIR only governs the sqlite db. The fastembed ONNX cache
# and the local-LLM GGUF cache (~656MB, openbmb/MiniCPM5-1B-GGUF) both
# live under ~/.hermes instead and ignore that var (see
# mnemosyne/core/embeddings.py, mnemosyne/core/local_llm.py) -- redirect
# HOME into the same persistent volume so neither cache re-downloads from
# HuggingFace on every container recreate.
ENV MNEMOSYNE_DATA_DIR=/data
ENV HOME=/data/home
VOLUME /data

COPY deploy/synology/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "from mnemosyne import recall; recall('health', top_k=1)" || exit 1

# Stays root until entrypoint.sh drops to the mnemosyne user via gosu --
# it needs root to usermod/chown at startup.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD []
