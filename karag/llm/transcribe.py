"""Voice → text via OpenAI's transcription endpoint.

Claude has no audio API, so voice notes are transcribed with the OpenAI key
(already required for embeddings) and the transcript joins the question text.
Audio bytes go only to the transcription endpoint — never to the generator.
"""

from __future__ import annotations

from ..errors import ConfigError, GenerationError


def sniff_audio_name(data: bytes, fallback: str = "voice-note.webm") -> str:
    """Pick a filename whose extension matches the actual container — the
    transcription API infers the codec from the filename, so a Firefox ogg
    recording named .webm would be rejected."""
    if data[:4] == b"OggS":
        return "voice-note.ogg"
    if data[:4] == b"\x1a\x45\xdf\xa3":  # EBML — webm/mkv
        return "voice-note.webm"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "voice-note.wav"
    if data[4:8] == b"ftyp":  # mp4/m4a
        return "voice-note.mp4"
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "voice-note.mp3"
    return fallback


def _httpx():
    try:
        import httpx  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise ConfigError("transcription requires httpx: pip install httpx") from exc
    return httpx


class OpenAITranscriber:
    def __init__(
        self,
        api_key: str | None,
        model: str = "gpt-4o-mini-transcribe",
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def transcribe(self, data: bytes, filename: str = "audio.webm") -> str:
        if not self._api_key:
            raise ConfigError("OPENAI_API_KEY is not set — cannot transcribe audio")
        httpx = _httpx()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                data={"model": self.model},
                files={"file": (filename, data)},
            )
            if resp.status_code != 200:
                raise GenerationError(
                    f"transcription failed ({resp.status_code}): {resp.text[:300]}"
                )
            return (resp.json().get("text") or "").strip()
