-- KARAG PostgreSQL + pgvector schema (production knowledge plane).
-- Apply once per deployment. Adjust the vector dimension to your embedder
-- (nomic-embed-text = 768, Voyage voyage-3 = 1024, OpenAI 3-large = 3072).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS karag_chunks (
    id           text PRIMARY KEY,
    document_id  text        NOT NULL,
    tenant_id    text        NOT NULL,
    data_class   text        NOT NULL,
    ordinal      integer     NOT NULL,
    title        text        NOT NULL,
    source_uri   text,
    text         text        NOT NULL,
    embedding    vector(768) NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- Tenant + class are the security-critical filter columns; index them so the
-- WHERE clause is cheap and the ANN scan only runs over the caller's slice.
CREATE INDEX IF NOT EXISTS karag_chunks_tenant_class_idx
    ON karag_chunks (tenant_id, data_class);

CREATE INDEX IF NOT EXISTS karag_chunks_document_idx
    ON karag_chunks (tenant_id, document_id);

-- Cosine ANN index. Rebuild lists/probes for your data size.
CREATE INDEX IF NOT EXISTS karag_chunks_embedding_idx
    ON karag_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
