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
# matches this platform; purged after the pip installs below.
#
# libgomp1 is named explicitly even though build-essential already pulls
# it in as a gcc dependency. llama_cpp's libllama.so links against it at
# *runtime*, but as an auto-installed dependency it was swept away by the
# `purge --auto-remove` below -- leaving an image where importing
# llama_cpp raises `libgomp.so.1: cannot open shared object file`.
# Naming it here marks it manually-installed, which --auto-remove spares.
RUN apt-get update && apt-get install -y --no-install-recommends \
      gosu build-essential cmake git libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# uid/gid 1000 here is just a placeholder -- entrypoint.sh rewrites both
# to PUID/PGID at container start (default: same setup as the
# linuxserver.io syncthing/plex images already on Trevor), so the bind
# mount ends up owned by whichever Synology account you point it at
# instead of a hardcoded guess.
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin mnemosyne

# Cache-friendly split: pre-install the [all] extras' actual third-party
# packages -- this is what pays for llama-cpp-python's from-source compile
# -- in their own layer, BEFORE the app wheel below. The wheel is rebuilt
# from the full source tree on every commit, so its checksum (and thus
# Docker's cache key) changes every time, regardless of whether any
# dependency version moved. Without this split, `pip install <wheel>[all]`
# would recompile llama-cpp-python from scratch on every single commit,
# even a one-line doc change. Keep this list in sync with pyproject.toml's
# [project.optional-dependencies] "all" entry.
RUN pip install --no-cache-dir \
      "ctransformers>=0.2.27" \
      "llama-cpp-python>=0.2.0" \
      "huggingface-hub>=0.20" \
      "fastembed>=0.3.0" \
      "sqlite-vec>=0.1.0" \
      "mcp>=1.0.0" \
      "anyio>=4.0" \
      "cryptography>=41.0"

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

# Deliberately its own layer, below the expensive installs above: the
# llama-cpp-python wheel compiles from source here (~20 min on this host,
# no manylinux wheel on PyPI), so anything that invalidates that layer
# costs a full recompile. anthropic is a pure-Python wheel -- installing it
# last means bumping it rebuilds seconds, not minutes. Same reasoning as
# the [all]-extras split above; see also the libgomp1 note near the top,
# which is the counter-example that cost a full rebuild.
RUN pip install --no-cache-dir "anthropic>=0.40"

# Lives under deploy/synology/ rather than scripts/ because .dockerignore
# excludes the whole scripts/ tree -- an explicit COPY from there fails the
# build with "not found", since the path never enters the build context.
COPY deploy/synology/claude_sleep.py /usr/local/bin/claude_sleep.py

COPY deploy/synology/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "from mnemosyne import recall; recall('health', top_k=1)" || exit 1

# Stays root until entrypoint.sh drops to the mnemosyne user via gosu --
# it needs root to usermod/chown at startup.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD []
