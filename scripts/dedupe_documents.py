"""Remove duplicate documents left over from before title-based replacement.

Re-adding a document with the same title now replaces the earlier copy, but a
database filled before that change may still hold several copies of the same
title (the console showed seven "Q2 Financials"). Duplicates fill every
retrieval slot with the same passage, so the assistant sees one document five
times and the others not at all.

    PYTHONPATH=. python scripts/dedupe_documents.py --tenant koinoti          # plan only
    PYTHONPATH=. python scripts/dedupe_documents.py --tenant koinoti --apply  # delete

Keeps, per title (case-insensitive), the copy with the most chunks — the most
complete one — and deletes the rest. Reads the same KARAG_* environment the
server uses, so run it with the server's .env loaded.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict

from karag.config import Settings
from karag.domain import DataClass
from karag.factory import build_store


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--apply", action="store_true", help="actually delete")
    args = ap.parse_args()

    store = build_store(Settings.from_env())
    docs = await store.list_documents(
        tenant_id=args.tenant, allowed_classes=frozenset(DataClass)
    )
    by_title: dict[str, list] = defaultdict(list)
    for d in docs:
        by_title[" ".join(d.title.split()).casefold()].append(d)

    removed = 0
    for title, copies in sorted(by_title.items()):
        if len(copies) < 2:
            continue
        keep = max(copies, key=lambda d: d.chunks)
        losers = [d for d in copies if d.document_id != keep.document_id]
        print(f"{title!r}: {len(copies)} copies — keep {keep.document_id} "
              f"({keep.chunks} chunks), drop {len(losers)}")
        for d in losers:
            if args.apply:
                n = await store.delete_document(
                    tenant_id=args.tenant, document_id=d.document_id
                )
                print(f"  deleted {d.document_id} ({n} chunks)")
            removed += 1
    if removed == 0:
        print("no duplicates found")
    elif not args.apply:
        print(f"{removed} duplicate(s) would be removed — re-run with --apply")


if __name__ == "__main__":
    asyncio.run(main())
