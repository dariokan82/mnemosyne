# Mnemosyne MCP Server — hardened, build-from-source image
#
# Unlike upstream's Dockerfile (which does `pip install mnemosyne-memory`
# from the floating PyPI package), this builds the wheel from this repo's
# own pinned checkout. The image only changes when this fork's source
# changes — not whenever a new PyPI release ships.
#
# Pinned baseline: v3.14.0 (mnemosyne-oss/mnemosyne @ 4e5ed14).
#
# Build:
#   docker build -t mnemosyne-mcp:v3.14.0 .
#
# Run (SSE — remote MCP over a tunnel, see docker-compose.yml):
#   docker compose up -d
#
# Run (stdio — Claude Desktop, Cursor, etc.):
#   docker run -i --rm -v mnemosyne-data:/data mnemosyne-mcp

FROM python:3.11-slim AS builder

WORKDIR /build
COPY . .
RUN pip install --no-cache-dir build && python -m build --wheel

FROM python:3.11-slim

LABEL org.opencontainers.image.title="Mnemosyne MCP Server (hardened fork build)"
LABEL org.opencontainers.image.description="Universal memory layer MCP server for any AI agent — built from source, pinned to v3.14.0"
LABEL org.opencontainers.image.source="https://github.com/dariokan82/mnemosyne"
LABEL org.opencontainers.image.licenses="MIT"

# Run as non-root — this container is reachable from the internet via the tunnel
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin mnemosyne

COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir "$(ls /tmp/*.whl)[mcp]" && rm -rf /tmp/*.whl

ENV MNEMOSYNE_DATA_DIR=/data
VOLUME /data
RUN mkdir -p /data && chown mnemosyne:mnemosyne /data

USER mnemosyne

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "from mnemosyne import recall; recall('health', top_k=1)" || exit 1

ENTRYPOINT ["mnemosyne", "mcp"]
CMD []
