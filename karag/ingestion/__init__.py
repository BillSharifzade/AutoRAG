"""Document ingestion: extract text from real files into the knowledge plane.

Supports .txt/.md/.csv and the OOXML formats (.docx/.xlsx/.pptx) with the
standard library only (they are zip packages of XML). PDF is supported when
``pypdf`` is installed. Used by ``IngestionService.ingest_file``.
"""

from .readers import SUPPORTED_EXTENSIONS, extract_text, UnsupportedFormat

__all__ = ["extract_text", "SUPPORTED_EXTENSIONS", "UnsupportedFormat"]
