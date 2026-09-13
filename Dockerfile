FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src/ src/

RUN pip install --no-cache-dir uv && \
    uv sync --no-dev --frozen && \
    rm -rf /root/.cache

ENV UNRAID_TRANSPORT=http \
    FASTMCP_HOST=0.0.0.0 \
    FASTMCP_PORT=8000

EXPOSE 8000

CMD ["uv", "run", "python", "-m", "unraid_mcp"]
