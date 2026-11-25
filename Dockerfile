# syntax=docker/dockerfile:1
# KARAG API image: every /v1/* endpoint. The console is the Next.js app, which
# has its own image in web/.
FROM python:3.12-slim

WORKDIR /app

# curl backs the compose healthcheck the web container waits on.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first so edits to the source do not invalidate the pip layer.
COPY pyproject.toml README.md ./
COPY karag ./karag
RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir ".[api,anthropic,ollama,pgvector,mysql,secrets,ingestion,fast]"

COPY scripts ./scripts
COPY sql ./sql

# Non-root runtime user; /data is where the SQLite files live (a volume).
RUN useradd -m karag && mkdir -p /data && chown karag:karag /data
USER karag

ENV PYTHONPATH=/app \
    KARAG_HOST=0.0.0.0 \
    KARAG_PORT=8000

EXPOSE 8000

# serve.py, not `uvicorn karag.api.app:app` — it is the composition root that
# registers the file-authoring skills and chains env tokens with DB accounts.
CMD ["python", "scripts/serve.py"]
