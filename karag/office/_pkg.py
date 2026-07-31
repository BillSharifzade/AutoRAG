"""Shared helpers for building OOXML (zip) packages."""

from __future__ import annotations

import io
import zipfile


def xml_escape(value: object) -> str:
    s = "" if value is None else str(value)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def col_letter(index_1based: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA … (spreadsheet column letters)."""
    n = index_1based
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def build_package(parts: dict[str, str | bytes]) -> bytes:
    """Zip a set of package parts into an OOXML file.

    ``[Content_Types].xml`` is written first, as some readers expect it there.
    """
    buf = io.BytesIO()
    ordered = sorted(parts, key=lambda p: (p != "[Content_Types].xml", p))
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in ordered:
            data = parts[name]
            zf.writestr(name, data if isinstance(data, bytes) else data.encode("utf-8"))
    return buf.getvalue()


_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="{target}"/></Relationships>'
)


def root_rels(target: str) -> str:
    return _RELS.format(target=target)
