"""Authoring skills — the model composes content, verified code renders bytes.

This is how "the assistant made me a file" works safely: the model calls one of
these tools with structured content; the actual xlsx/docx/pptx/pdf/text bytes
are produced by KARAG's own builders and attached to the answer out-of-band,
so binary data never flows through the model.

All skills are PUBLIC-class: they add no data access — they can only render
what the (already RBAC-filtered) conversation contains.
"""

from __future__ import annotations

import mimetypes
import re

from ..domain import Artifact, DataClass, Principal
from ..office import OfficeService
from ..office.pdf import build_pdf
from .base import Skill, SkillResult

_office = OfficeService()

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
# text-file extensions the write_file skill will emit (code, config, docs)
_TEXT_EXTS = {
    "txt", "md", "markdown", "csv", "json", "yaml", "yml", "toml", "ini", "xml",
    "html", "css", "js", "jsx", "ts", "tsx", "py", "rs", "go", "java", "kt",
    "c", "h", "cpp", "hpp", "cs", "rb", "php", "swift", "sql", "sh", "bash",
    "ps1", "bat", "dockerfile", "env", "cfg", "log", "tex", "r", "lua", "pl",
}


def _safe_name(filename: str, default_ext: str = "txt") -> str:
    name = _SAFE_NAME.sub("_", (filename or "").strip()).strip("._") or "file"
    if "." not in name:
        name = f"{name}.{default_ext}"
    return name[:120]


async def _write_file(principal: Principal, args: dict) -> SkillResult:
    filename = _safe_name(str(args.get("filename", "")))
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in _TEXT_EXTS:
        filename = f"{filename}.txt"
        ext = "txt"
    content = str(args.get("content", ""))
    mime = mimetypes.guess_type(filename)[0] or "text/plain"
    artifact = Artifact(
        filename=filename, mime=mime, content=content.encode("utf-8")
    )
    return SkillResult(
        data={"filename": filename, "bytes": len(artifact.content)},
        query_shown=f"write_file(filename={filename!r})",
        artifact=artifact,
    )


async def _create_spreadsheet(principal: Principal, args: dict) -> SkillResult:
    fmt = str(args.get("format", "xlsx")).lower()
    if fmt not in ("xlsx", "csv"):
        fmt = "xlsx"
    artifact = _office.report(
        title=str(args.get("title", "Spreadsheet")),
        headers=[str(h) for h in args.get("headers", [])],
        rows=[list(r) for r in args.get("rows", [])],
        fmt=fmt,
    )
    return SkillResult(
        data={"filename": artifact.filename, "rows": len(args.get("rows", []))},
        query_shown=f"create_spreadsheet(title={args.get('title')!r}, format={fmt!r})",
        artifact=artifact,
    )


async def _create_document(principal: Principal, args: dict) -> SkillResult:
    artifact = _office.report(
        title=str(args.get("title", "Document")),
        headers=[str(h) for h in args.get("table_headers", [])],
        rows=[list(r) for r in args.get("table_rows", [])],
        paragraphs=[str(p) for p in args.get("paragraphs", [])],
        fmt="docx",
    )
    return SkillResult(
        data={"filename": artifact.filename},
        query_shown=f"create_document(title={args.get('title')!r})",
        artifact=artifact,
    )


async def _create_presentation(principal: Principal, args: dict) -> SkillResult:
    slides = [
        {
            "title": str(s.get("title", "")),
            "bullets": [str(b) for b in s.get("bullets", [])],
        }
        for s in args.get("slides", [])
    ]
    artifact = _office.deck(
        title=str(args.get("title", "Presentation")),
        subtitle=str(args.get("subtitle", "")),
        slides=slides,
    )
    return SkillResult(
        data={"filename": artifact.filename, "slides": len(slides) + 1},
        query_shown=f"create_presentation(title={args.get('title')!r}, slides={len(slides)})",
        artifact=artifact,
    )


async def _create_pdf(principal: Principal, args: dict) -> SkillResult:
    title = str(args.get("title", "Document"))
    content = build_pdf(title, [str(p) for p in args.get("paragraphs", [])])
    stem = _SAFE_NAME.sub("_", title).strip("_") or "document"
    artifact = Artifact(
        filename=f"{stem[:80]}.pdf", mime="application/pdf", content=content
    )
    return SkillResult(
        data={"filename": artifact.filename, "bytes": len(content)},
        query_shown=f"create_pdf(title={title!r})",
        artifact=artifact,
    )


def write_file_skill(tenant_id: str = "*") -> Skill:
    return Skill(
        category="output",
        name="write_file",
        description=(
            "Create a downloadable plain-text file for the user: markdown, source "
            "code in any language, JSON/YAML/CSV, SQL, HTML, config files, etc. "
            "Give the full desired content; the file is attached to your answer."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name with extension, e.g. notes.md or script.py",
                },
                "content": {"type": "string", "description": "Full file content"},
            },
            "required": ["filename", "content"],
        },
        handler=_write_file,
        required_data_class=DataClass.PUBLIC,
        tenant_id=tenant_id,
    )


def create_spreadsheet_skill(tenant_id: str = "*") -> Skill:
    return Skill(
        category="output",
        name="create_spreadsheet",
        description=(
            "Create a downloadable Excel (.xlsx) or CSV spreadsheet from headers "
            "and rows you provide."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "headers": {"type": "array", "items": {"type": "string"}},
                "rows": {"type": "array", "items": {"type": "array"}},
                "format": {"type": "string", "enum": ["xlsx", "csv"]},
            },
            "required": ["title", "headers", "rows"],
        },
        handler=_create_spreadsheet,
        required_data_class=DataClass.PUBLIC,
        tenant_id=tenant_id,
    )


def create_document_skill(tenant_id: str = "*") -> Skill:
    return Skill(
        category="output",
        name="create_document",
        description=(
            "Create a downloadable Word document (.docx) from a title and "
            "paragraphs, with an optional table. Use this for letters, reports, "
            "policies — including Cyrillic or any non-Latin text."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "paragraphs": {"type": "array", "items": {"type": "string"}},
                "table_headers": {"type": "array", "items": {"type": "string"}},
                "table_rows": {"type": "array", "items": {"type": "array"}},
            },
            "required": ["title", "paragraphs"],
        },
        handler=_create_document,
        required_data_class=DataClass.PUBLIC,
        tenant_id=tenant_id,
    )


def create_presentation_skill(tenant_id: str = "*") -> Skill:
    return Skill(
        category="output",
        name="create_presentation",
        description=(
            "Create a downloadable PowerPoint (.pptx) deck: a branded cover plus "
            "one slide per {title, bullets} you provide."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "subtitle": {"type": "string"},
                "slides": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "bullets": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["title"],
                    },
                },
            },
            "required": ["title", "slides"],
        },
        handler=_create_presentation,
        required_data_class=DataClass.PUBLIC,
        tenant_id=tenant_id,
    )


def create_pdf_skill(tenant_id: str = "*") -> Skill:
    return Skill(
        category="output",
        name="create_pdf",
        description=(
            "Create a downloadable PDF from a title and paragraphs. Latin text "
            "only (built-in PDF fonts) — for Cyrillic or other scripts use "
            "create_document (.docx) instead."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "paragraphs": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "paragraphs"],
        },
        handler=_create_pdf,
        required_data_class=DataClass.PUBLIC,
        tenant_id=tenant_id,
    )


def authoring_skills(tenant_id: str = "*") -> list[Skill]:
    """The full set, ready to register."""
    return [
        write_file_skill(tenant_id),
        create_spreadsheet_skill(tenant_id),
        create_document_skill(tenant_id),
        create_presentation_skill(tenant_id),
        create_pdf_skill(tenant_id),
    ]
