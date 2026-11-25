"""Reading scanned PDFs with Claude.

A PDF that is a stack of page images has no text layer, so ``pypdf`` returns
nothing and the document could never be found. Claude reads PDF pages as
images natively; this asks it to transcribe them, keeping headings and tables
in Markdown so section-aware chunking still works on the result.

Long scans are sent in batches of pages (split with ``pypdf``) so a single
transcription never runs into the output limit. The default model is the
small, inexpensive one: transcription needs good eyes, not deep reasoning.

Privacy note: the whole document goes to the API, where ordinary questions
only send the few passages they retrieve. ``KARAG_PDF_OCR=off`` refuses
scanned PDFs instead.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging

from ..errors import GenerationError

log = logging.getLogger("karag.llm.ocr")

PAGES_PER_REQUEST = 40

_PROMPT = (
    "Transcribe all the text in this document exactly as written, in its "
    "original language. Do not translate, summarise or correct anything. "
    "Write headings as Markdown '#' lines and tables as Markdown tables. "
    "Separate pages with a blank line. Output only the transcription."
)


def _batches(data: bytes, size: int) -> list[bytes]:
    try:
        from pypdf import PdfReader, PdfWriter  # noqa: PLC0415
    except ImportError:
        return [data]
    reader = PdfReader(io.BytesIO(data))
    if len(reader.pages) <= size:
        return [data]
    out: list[bytes] = []
    for start in range(0, len(reader.pages), size):
        writer = PdfWriter()
        for page in reader.pages[start : start + size]:
            writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        out.append(buf.getvalue())
    return out


class ClaudePdfReader:
    def __init__(
        self,
        *,
        model: str = "claude-haiku-5-5",
        api_key: str | None = None,
        workspace_id: str | None = None,
        max_tokens: int = 64000,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._workspace_id = workspace_id
        self.max_tokens = max_tokens

    def _client(self):
        try:
            import anthropic  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise GenerationError("PDF reading requires the anthropic SDK") from exc
        kwargs: dict = {}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._workspace_id:
            kwargs["default_headers"] = {"anthropic-workspace-id": self._workspace_id}
        return anthropic, anthropic.AsyncAnthropic(**kwargs)

    async def __call__(self, data: bytes) -> str:
        anthropic, client = self._client()
        parts = await asyncio.to_thread(_batches, data, PAGES_PER_REQUEST)
        texts: list[str] = []
        try:
            for part in parts:
                async with client.messages.stream(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    output_config={"effort": "low"},
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": base64.standard_b64encode(part).decode(),
                                },
                            },
                            {"type": "text", "text": _PROMPT},
                        ],
                    }],
                ) as stream:
                    msg = await stream.get_final_message()
                if msg.stop_reason == "refusal":
                    raise GenerationError("the model declined to read this document")
                texts.append("".join(b.text for b in msg.content if b.type == "text"))
        except anthropic.APIError as exc:
            raise GenerationError(f"PDF reading failed: {exc}") from exc
        finally:
            await client.close()
        return "\n\n".join(t.strip() for t in texts if t.strip())
