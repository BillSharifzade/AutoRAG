"""Re-embed existing passages with their context (title + section heading).

Passages ingested before contextual embeddings were embedded as bare text.
Keyword search needs nothing (its index is backfilled on start-up), but the
vector side improves once every passage is embedded the way new ones are:
"<title> — <heading>\\n\\n<passage>". Old passages have no recorded heading,
so they gain their title; re-uploading a document also restores headings.

Dry run by default — it reports what it would do. Works on the sqlite and
pgvector stores; costs one embedding call per 64 passages.

    set -a; source .env; set +a
    PYTHONPATH=. .venv/bin/python scripts/reindex_documents.py            # dry run
    PYTHONPATH=. .venv/bin/python scripts/reindex_documents.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3

from karag.config import Settings
from karag.factory import build_embedder
from karag.knowledge.ingest import embedding_text

BATCH = 64


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the new embeddings")
    ap.add_argument("--tenant", help="only this tenant")
    args = ap.parse_args()

    s = Settings.from_env()
    embedder = build_embedder(s)

    if s.store == "sqlite":
        from karag.vectorstore.sqlite import SqliteVectorStore, _pack

        SqliteVectorStore(s.sqlite_path)  # runs the schema migrations first
        conn = sqlite3.connect(s.sqlite_path)
        where, params = ("WHERE tenant_id = ?", (args.tenant,)) if args.tenant else ("", ())
        rows = conn.execute(
            f"SELECT id, title, heading, text FROM karag_chunks {where}", params
        ).fetchall()

        async def write(batch, vecs):
            conn.executemany(
                "UPDATE karag_chunks SET embedding = ? WHERE id = ?",
                [(_pack(v), r[0]) for r, v in zip(batch, vecs)],
            )
            conn.commit()

    elif s.store == "pgvector":
        import psycopg

        from karag.vectorstore.pgvector import PgVectorStore, _vec_literal

        store = PgVectorStore(s.pg_dsn)
        await store._ready()  # adds heading/terms if missing
        conn = psycopg.connect(s.pg_dsn)
        where, params = ("WHERE tenant_id = %s", (args.tenant,)) if args.tenant else ("", ())
        rows = conn.execute(
            f"SELECT id, title, heading, text FROM karag_chunks {where}", params
        ).fetchall()

        async def write(batch, vecs):
            with conn.cursor() as cur:
                cur.executemany(
                    "UPDATE karag_chunks SET embedding = %s::vector WHERE id = %s",
                    [(_vec_literal(v), r[0]) for r, v in zip(batch, vecs)],
                )
            conn.commit()

    else:
        raise SystemExit(f"store {s.store!r} keeps nothing on disk — nothing to re-index")

    print(f"{len(rows)} passages in {s.store} ({type(embedder).__name__}, dim {embedder.dim})")
    if not args.apply:
        print("dry run — add --apply to re-embed them")
        return
    done = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        vecs = await embedder.embed([embedding_text(t, h or "", x) for _, t, h, x in batch])
        await write(batch, vecs)
        done += len(batch)
        print(f"  {done}/{len(rows)}")
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
