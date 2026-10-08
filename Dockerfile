FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src/ src/

RUN pip install --no-cache-dir uv && \
    uv sync --no-dev --frozen && \
    rm -rf /root/.cache

# Hardened runtime: runs as uid/gid 10078, meant for
#   --read-only --cap-drop ALL --security-opt no-new-privileges
# CMD calls the venv python directly: `uv run` would write a cache on a
# read-only root.  PYTHONDONTWRITEBYTECODE stops __pycache__ writes.
#
# HTTP transport fails closed (see README "HTTP authentication"):
# - Mount the appdata directory read-only at /config, owned by 10078, mode 0700.
#   It must hold both secret files:
#     /config/http-token        bearer token (>= 43 chars, b64token charset)
#     /config/unraid-api.key    Unraid API key
#   Each must be a regular file, mode 0600, owned by 10078 (the owner must be
#   the effective uid).
# - Remove UNRAID_API_KEY from the container template: with UNRAID_API_KEY_FILE
#   also set the container refuses to start (ambiguous key source).
# - The image sets no bind: without MCP_HOST/MCP_PORT it binds 127.0.0.1:8000,
#   so a host-network container that lost its template never listens on every
#   interface.
# Monolith example (host network, canonical template deploy/my-unraid-mcp.xml):
#   MCP_HOST=10.10.10.50 MCP_PORT=8078 MCP_ALLOWED_HOSTS=10.10.10.50
#   MCP_ALLOWED_CLIENTS=192.168.0.240 UNRAID_API_URL=http://127.0.0.1/graphql
# No EXPOSE: the port comes from MCP_PORT at run time and host networking
# ignores EXPOSE, so a fixed one would advertise the wrong port.
ENV UNRAID_TRANSPORT=http \
    MCP_AUTH_TOKEN_FILE=/config/http-token \
    UNRAID_API_KEY_FILE=/config/unraid-api.key \
    PYTHONDONTWRITEBYTECODE=1

USER 10078:10078

CMD ["/app/.venv/bin/python", "-m", "unraid_mcp"]
