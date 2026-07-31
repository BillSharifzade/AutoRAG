"""OfficeService — turn a title + tabular data into an Artifact in any format."""

from __future__ import annotations

import csv
import io
import re

from ..domain import Artifact
from .docx import build_docx
from .pptx import build_pptx
from .xlsx import build_xlsx

_MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "csv": "text/csv",
}

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(stem: str, ext: str) -> str:
    stem = _SAFE.sub("_", stem).strip("_") or "report"
    return f"{stem[:80]}.{ext}"


class OfficeService:
    def report(
        self,
        *,
        title: str,
        headers: list[str],
        rows: list[list[object]],
        fmt: str = "xlsx",
        paragraphs: list[str] | None = None,
    ) -> Artifact:
        fmt = fmt.lower()
        if fmt not in _MIME:
            raise ValueError(f"unsupported format: {fmt}")

        if fmt == "xlsx":
            content = build_xlsx({"Report": [headers, *rows] if headers else list(rows)})
        elif fmt == "docx":
            content = build_docx(
                title=title,
                paragraphs=paragraphs,
                table_headers=headers,
                table_rows=rows,
            )
        elif fmt == "pptx":
            content = self._table_deck(title, headers, rows, paragraphs)
        else:  # csv
            content = self._csv(headers, rows)

        return Artifact(
            filename=_safe_filename(title, fmt),
            mime=_MIME[fmt],
            content=content,
        )

    def deck(self, *, title: str, slides: list[dict], subtitle: str = "") -> Artifact:
        """Build a presentation from explicit slides ({title, bullets})."""
        cover = {"title": title, "bullets": [], "layout": "title", "subtitle": subtitle}
        content = build_pptx([cover, *slides])
        return Artifact(
            filename=_safe_filename(title, "pptx"), mime=_MIME["pptx"], content=content
        )

    @staticmethod
    def _table_deck(
        title: str, headers: list[str], rows: list[list[object]], paragraphs: list[str] | None
    ) -> bytes:
        header = " | ".join(str(h) for h in headers) if headers else ""
        bullets = [header] if header else []
        bullets += [" | ".join("" if c is None else str(c) for c in r) for r in rows]
        content_slide = {"title": "Details", "bullets": bullets, "footer": title}
        cover = {
            "title": title, "bullets": [], "layout": "title",
            "subtitle": " · ".join(paragraphs or []),
        }
        return build_pptx([cover, content_slide])

    @staticmethod
    def _csv(headers: list[str], rows: list[list[object]]) -> bytes:
        buf = io.StringIO()
        w = csv.writer(buf)
        if headers:
            w.writerow(headers)
        for row in rows:
            w.writerow(["" if c is None else c for c in row])
        return buf.getvalue().encode("utf-8")
