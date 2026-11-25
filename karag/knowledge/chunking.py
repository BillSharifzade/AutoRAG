"""Deterministic, dependency-free text chunking.

Two layers:

* :func:`chunk_text` packs sentence/paragraph units into overlapping windows
  bounded by ``max_chars``. Overlap preserves context across boundaries so a
  passage split mid-topic is still retrievable from either side.
* :func:`chunk_document` first splits a document into its sections (Markdown
  ``#`` headings — the readers turn Word headings into those) and chunks each
  section on its own, so a passage never straddles two topics and always knows
  the heading it sits under. A table is split between rows, never inside one,
  and every piece of it repeats the header row — "4 200" means nothing
  without the "Оклад" column above it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SPLIT = re.compile(r"(?<=[.!?])\s+|\n{2,}")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_TABLE_LINE = re.compile(r"^\s*\|")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}")

HEADING_SEP = " › "


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


@dataclass
class Piece:
    """One chunk of a document and the section it belongs to."""

    text: str
    heading: str = ""


def split_sections(text: str) -> list[tuple[str, str]]:
    """``[(heading path, section body)]`` in document order.

    The path joins the nested headings (``Раздел › Подраздел``); text before
    the first heading has an empty path.
    """
    path: list[str] = []
    sections: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            sections.append((HEADING_SEP.join(path), body))
        buf.clear()

    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            path = path[: level - 1] + [m.group(2).strip()]
        else:
            buf.append(line)
    flush()
    return sections


def _blocks(body: str) -> list[tuple[str, str]]:
    """Split a section into ("text"|"table", content) blocks."""
    blocks: list[tuple[str, str]] = []
    text_buf: list[str] = []
    table_buf: list[str] = []
    for line in body.splitlines():
        if _TABLE_LINE.match(line):
            if text_buf:
                blocks.append(("text", "\n".join(text_buf)))
                text_buf = []
            table_buf.append(line)
        else:
            if table_buf:
                blocks.append(("table", "\n".join(table_buf)))
                table_buf = []
            text_buf.append(line)
    if table_buf:
        blocks.append(("table", "\n".join(table_buf)))
    if text_buf:
        blocks.append(("text", "\n".join(text_buf)))
    return [(k, v) for k, v in blocks if v.strip()]


def _split_table(table: str, max_chars: int) -> list[str]:
    lines = [ln for ln in table.splitlines() if ln.strip()]
    if len(table) <= max_chars or len(lines) < 3:
        return [table]
    header = lines[:2] if _TABLE_RULE.match(lines[1]) else lines[:1]
    rows = lines[len(header):]
    head = "\n".join(header)
    out: list[str] = []
    cur: list[str] = []
    for row in rows:
        if cur and len(head) + sum(len(r) + 1 for r in cur) + len(row) + 1 > max_chars:
            out.append(head + "\n" + "\n".join(cur))
            cur = []
        cur.append(row)
    if cur:
        out.append(head + "\n" + "\n".join(cur))
    return out


def chunk_document(
    text: str, *, max_chars: int = 800, overlap: int = 120
) -> list[Piece]:
    """Chunk a whole document section by section (see the module docstring)."""
    pieces: list[Piece] = []
    for heading, body in split_sections(text) or [("", text)]:
        pending = ""  # short text blocks are packed together
        for kind, content in _blocks(body):
            if kind == "table":
                if pending:
                    pieces.extend(Piece(c, heading) for c in chunk_text(
                        pending, max_chars=max_chars, overlap=overlap))
                    pending = ""
                pieces.extend(Piece(c, heading) for c in _split_table(content, max_chars))
            else:
                pending = f"{pending}\n\n{content}".strip() if pending else content.strip()
        if pending:
            pieces.extend(Piece(c, heading) for c in chunk_text(
                pending, max_chars=max_chars, overlap=overlap))
    return pieces
