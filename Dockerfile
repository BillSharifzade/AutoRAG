# KARAG service image.
FROM python:3.12-slim

WORKDIR /app

# System deps kept minimal; wheels cover psycopg[binary]/httpx.
COPY pyproject.toml README.md ./
COPY karag ./karag
COPY sql ./sql

RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir ".[api,anthropic,ollama,pgvector,ingestion]"

# Non-root runtime user.
RUN useradd -m karag
USER karag

EXPOSE 8000

# Provider config is supplied via environment (see .env.example).
CMD ["uvicorn", "karag.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
