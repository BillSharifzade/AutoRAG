"""Office document generation (Phase 1.5) — the "ready business document" wow.

Produces genuinely valid .xlsx / .docx files (and .csv) as OOXML zip packages
using *only the standard library*. No third-party dependency, no code execution
sandbox required — so report generation is fast, deterministic, and testable
offline. Output skills return these as :class:`~karag.domain.Artifact`.
"""

from .service import OfficeService

__all__ = ["OfficeService"]
