"""Minimal PDF writer — pure stdlib, valid PDF 1.4.

Text-only pages using the built-in Helvetica fonts (WinAnsi encoding, so
Latin scripts only — Cyrillic callers should produce .docx instead). Follows
the same philosophy as the other office builders: bytes are produced by
verified code, never by the model.
"""

from __future__ import annotations

import textwrap

_PAGE_W, _PAGE_H = 612, 792  # US Letter, points
_MARGIN = 56
_BODY_SIZE = 11
_TITLE_SIZE = 18
_LEADING = 16
_WRAP = 92
_LINES_PER_PAGE = int((_PAGE_H - 2 * _MARGIN - _TITLE_SIZE - 14) / _LEADING)


def _esc(text: str) -> str:
    safe = text.encode("cp1252", errors="replace").decode("cp1252")
    return safe.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _wrap_paragraphs(paragraphs: list[str]) -> list[str]:
    lines: list[str] = []
    for p in paragraphs:
        p = (p or "").strip()
        if not p:
            lines.append("")
            continue
        lines.extend(textwrap.wrap(p, _WRAP) or [""])
        lines.append("")
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _page_stream(title: str | None, lines: list[str]) -> bytes:
    y = _PAGE_H - _MARGIN
    parts = ["BT"]
    if title is not None:
        parts.append(f"/F2 {_TITLE_SIZE} Tf 1 0 0 1 {_MARGIN} {y - _TITLE_SIZE} Tm")
        parts.append(f"({_esc(title)}) Tj")
        y -= _TITLE_SIZE + 22
    parts.append(f"/F1 {_BODY_SIZE} Tf 1 0 0 1 {_MARGIN} {y - _BODY_SIZE} Tm")
    parts.append(f"{_LEADING} TL")
    for line in lines:
        parts.append(f"({_esc(line)}) Tj T*")
    parts.append("ET")
    return "\n".join(parts).encode("cp1252", errors="replace")


def build_pdf(title: str, paragraphs: list[str]) -> bytes:
    lines = _wrap_paragraphs(paragraphs)
    pages_lines = [lines[i : i + _LINES_PER_PAGE] for i in range(0, len(lines), _LINES_PER_PAGE)] or [[]]

    # object numbering: 1 catalog, 2 pages, 3 F1, 4 F2, then per page: page obj, content obj
    objects: dict[int, bytes] = {}
    page_ids = []
    next_id = 5
    for idx, page in enumerate(pages_lines):
        page_id, content_id = next_id, next_id + 1
        next_id += 2
        page_ids.append(page_id)
        stream = _page_stream(title if idx == 0 else None, page)
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PAGE_W} {_PAGE_H}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode()

    kids = " ".join(f"{p} 0 R" for p in page_ids)
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    objects[4] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for oid in sorted(objects):
        offsets[oid] = len(out)
        out += f"{oid} 0 obj\n".encode() + objects[oid] + b"\nendobj\n"

    xref_at = len(out)
    count = len(objects) + 1
    out += f"xref\n0 {count}\n".encode()
    out += b"0000000000 65535 f \n"
    for oid in sorted(objects):
        out += f"{offsets[oid]:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)
