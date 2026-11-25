-- KARAG PostgreSQL + pgvector schema (production knowledge plane).
-- Apply once per deployment. Adjust the vector dimension to your embedder
-- (nomic-embed-text = 768, Voyage voyage-3 = 1024, OpenAI 3-large with
-- KARAG_EMBED_DIM=1024 = 1024). Indexed vectors are limited to 2000 dims.
--
-- An existing table is upgraded by the store itself on first use (heading,
-- terms and the keyword index are added and backfilled); only the HNSW index
-- below is left to you, because building it on a large table takes a while.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS karag_chunks (
    id           text PRIMARY KEY,
    document_id  text         NOT NULL,
    tenant_id    text         NOT NULL,
    data_class   text         NOT NULL,
    ordinal      integer      NOT NULL,
    title        text         NOT NULL,
    source_uri   text,
    text         text         NOT NULL,
    heading      text         NOT NULL DEFAULT '',
    -- stemmed keyword terms (karag.knowledge.lexical), searched with FTS
    terms        text,
    embedding    vector(1024) NOT NULL,
    created_at   timestamptz  NOT NULL DEFAULT now()
);

-- Tenant + class are the security-critical filter columns; index them so the
-- WHERE clause is cheap and the ANN scan only runs over the caller's slice.
CREATE INDEX IF NOT EXISTS karag_chunks_tenant_class_idx
    ON karag_chunks (tenant_id, data_class);

CREATE INDEX IF NOT EXISTS karag_chunks_document_idx
    ON karag_chunks (tenant_id, document_id);

-- Cosine ANN index. HNSW keeps good recall without tuning and can be built on
-- an empty table (ivfflat's lists are learned from the rows present at build
-- time, so building it before any data gives poor recall). Replacing an older
-- ivfflat index:
--   DROP INDEX IF EXISTS karag_chunks_embedding_idx;
CREATE INDEX IF NOT EXISTS karag_chunks_embedding_hnsw_idx
    ON karag_chunks USING hnsw (embedding vector_cosine_ops);

-- Keyword search over the stemmed terms.
CREATE INDEX IF NOT EXISTS karag_chunks_terms_idx
    ON karag_chunks USING gin (to_tsvector('simple', coalesce(terms, '')));
