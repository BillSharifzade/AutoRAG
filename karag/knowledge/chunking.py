"""Deterministic, dependency-free text chunking.

Packs sentence/paragraph units into overlapping windows bounded by
``max_chars``. Overlap preserves context across boundaries so a passage split
mid-topic is still retrievable from either side.
"""

from __future__ import annotations

import re

_SPLIT = re.compile(r"(?<=[.!?])\s+|\n{2,}")


def chunk_text(text: str, *, max_chars: int = 800, overlap: int = 120) -> list[str]:
    text = text.strip()
    if not text:
        return []
    units = [u.strip() for u in _SPLIT.split(text) if u and u.strip()]
    if not units:
        units = [text]

    chunks: list[str] = []
    buf = ""
    for unit in units:
        if not buf:
            buf = unit
        elif len(buf) + 1 + len(unit) <= max_chars:
            buf = f"{buf} {unit}"
        else:
            chunks.append(buf)
            tail = buf[-overlap:] if overlap > 0 else ""
            buf = f"{tail} {unit}".strip() if tail else unit
    if buf:
        chunks.append(buf)

    # Hard-split any single unit that exceeds max_chars on its own.
    out: list[str] = []
    for c in chunks:
        if len(c) <= max_chars:
            out.append(c)
        else:
            for i in range(0, len(c), max_chars - overlap):
                out.append(c[i : i + max_chars])
    return out
