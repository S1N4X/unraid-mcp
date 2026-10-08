FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src/ src/

RUN pip install --no-cache-dir uv && \
    uv sync --no-dev --frozen && \
    rm -rf /root/.cache

# HTTP transport fails closed (see README "HTTP authentication"):
# - Mount the appdata directory at /config.  It must hold both secret files:
#     /config/http-token        bearer token (>= 43 chars, b64token charset)
#     /config/unraid-api.key    Unraid API key
#   Each must be a regular file, mode 0600, owned by root (the container runs
#   as root, and the owner must be the effective uid).
# - FASTMCP_HOST=0.0.0.0 binds every interface, so MCP_ALLOWED_HOSTS is
#   required (e.g. MCP_ALLOWED_HOSTS=10.10.10.78); set MCP_ALLOWED_CLIENTS too.
# - Remove UNRAID_API_KEY from the container template: with UNRAID_API_KEY_FILE
#   also set the container refuses to start (ambiguous key source).
# MCP_HOST/MCP_PORT, when set, take precedence over FASTMCP_HOST/FASTMCP_PORT.
ENV UNRAID_TRANSPORT=http \
    FASTMCP_HOST=0.0.0.0 \
    FASTMCP_PORT=8000 \
    MCP_AUTH_TOKEN_FILE=/config/http-token \
    UNRAID_API_KEY_FILE=/config/unraid-api.key

EXPOSE 8000

CMD ["uv", "run", "python", "-m", "unraid_mcp"]
