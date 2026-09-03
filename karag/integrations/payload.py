"""Fetching and understanding an API payload.

The fetch goes through the same guard as web reading (no private addresses,
redirects re-checked hop by hop, a byte cap). What comes back is *profiled*
deterministically — the record list, the fields, their types, sample values —
so the description the model writes is anchored in facts, and so the platform
has something to show even when no model is available.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin

from ..errors import KaragError
from ..web.guard import WebAccessDenied, WebPolicy, check_url

MAX_PAYLOAD_BYTES = 4_000_000
# how much of the data a model or a knowledge document gets to see
SAMPLE_RECORDS = 8
MAX_DOC_RECORDS = 5000
MAX_DOC_CHARS = 400_000


class EndpointError(KaragError):
    """The endpoint answered, but not with data (4xx/5xx)."""
# JSON media types that servers actually send
_JSON_TYPES = ("application/json", "text/json", "+json")
_CSV_TYPES = ("text/csv", "application/csv")


@dataclass
class Payload:
    url: str
    content_type: str
    kind: str  # json | csv | text
    raw: bytes
    data: object  # parsed JSON, list[dict] for CSV, str for text
    fetched_at: float = field(default_factory=time.time)
    truncated: bool = False

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()


@dataclass
class FieldProfile:
    name: str
    types: list[str]
    samples: list[object]
    filled: int  # records where the field is present and not null

    def to_dict(self) -> dict:
        return {"name": self.name, "types": self.types, "samples": self.samples, "filled": self.filled}


@dataclass
class Profile:
    kind: str  # records | object | scalar | text
    record_count: int
    fields: list[FieldProfile]
    records_path: str  # where the record list lives ("" = root, "data", "items"…)
    sample: list  # a few records (or the object itself)
    text_preview: str = ""
    top_level_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "record_count": self.record_count,
            "fields": [f.to_dict() for f in self.fields],
            "records_path": self.records_path,
            "sample": self.sample,
            "text_preview": self.text_preview,
            "top_level_keys": self.top_level_keys,
        }


def _httpx():
    try:
        import httpx  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise KaragError("fetching an endpoint requires httpx: pip install httpx") from exc
    return httpx


async def fetch_payload(url: str, policy: WebPolicy | None = None) -> Payload:
    """GET ``url`` under the web policy and parse what comes back."""
    httpx = _httpx()
    policy = policy or WebPolicy()
    current = check_url(url, policy)
    async with httpx.AsyncClient(
        timeout=policy.timeout_s,
        follow_redirects=False,
        headers={
            "User-Agent": "KARAG/1.0 (+enterprise assistant)",
            "Accept": "application/json, text/csv;q=0.9, text/plain;q=0.8, */*;q=0.5",
        },
    ) as client:
        for _ in range(policy.max_redirects + 1):
            resp = await client.get(current)
            if resp.is_redirect:
                location = resp.headers.get("location", "")
                if not location:
                    raise WebAccessDenied("that address redirected to nowhere")
                current = check_url(urljoin(current, location), policy)
                continue
            if resp.status_code >= 400:
                raise EndpointError(f"the endpoint answered {resp.status_code} {resp.reason_phrase}")
            raw = resp.content[:MAX_PAYLOAD_BYTES]
            truncated = len(resp.content) > MAX_PAYLOAD_BYTES
            content_type = resp.headers.get("content-type", "").lower()
            break
        else:
            raise WebAccessDenied("that address redirected too many times")

    return parse_payload(str(resp.url), content_type, raw, truncated=truncated)


def parse_payload(url: str, content_type: str, raw: bytes, *, truncated: bool = False) -> Payload:
    """Turn bytes into structured data by content type, then by sniffing."""
    text = raw.decode("utf-8", errors="replace")
    base = content_type.split(";", 1)[0].strip()
    if any(t in base for t in _JSON_TYPES) or _looks_like_json(text):
        try:
            return Payload(url, content_type, "json", raw, json.loads(text), truncated=truncated)
        except json.JSONDecodeError:
            if truncated:
                raise KaragError(
                    "the endpoint returned more than the size limit and the cut-off "
                    "JSON cannot be read — ask for a smaller page of data"
                )
            # fall through: it said JSON but is not
    if base in _CSV_TYPES or (base in ("text/plain", "") and _looks_like_csv(text)):
        rows = list(csv.DictReader(io.StringIO(text)))
        if rows:
            return Payload(url, content_type, "csv", raw, rows, truncated=truncated)
    return Payload(url, content_type, "text", raw, text, truncated=truncated)


def _looks_like_json(text: str) -> bool:
    head = text.lstrip()[:1]
    return head in ("{", "[")


def _looks_like_csv(text: str) -> bool:
    lines = [ln for ln in text.splitlines()[:5] if ln.strip()]
    if len(lines) < 2:
        return False
    counts = {ln.count(",") for ln in lines}
    return len(counts) == 1 and counts.pop() >= 1


# ---------------------------------------------------------------- profiling


def find_records(payload: Payload) -> list:
    """The record list of a JSON or CSV payload (empty for text / a bare object)."""
    if payload.kind == "csv":
        return list(payload.data)
    if payload.kind == "json":
        return _find_records(payload.data)[0]
    return []


def _find_records(data: object) -> tuple[list, str]:
    """The list of records inside a JSON payload, and where it was found."""
    if isinstance(data, list):
        return data, ""
    if isinstance(data, dict):
        # the biggest list of objects one level down is the payload's substance
        best: tuple[list, str] | None = None
        for key, value in data.items():
            if isinstance(value, list) and value and all(isinstance(v, dict) for v in value[:20]):
                if best is None or len(value) > len(best[0]):
                    best = (value, key)
        if best is not None:
            return best
        # one level deeper ("data": {"items": [...]})
        for key, value in data.items():
            if isinstance(value, dict):
                inner, path = _find_records(value)
                if inner and path:
                    return inner, f"{key}.{path}"
    return [], ""


def _type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _short(value: object, limit: int = 80) -> object:
    if isinstance(value, str):
        return value if len(value) <= limit else value[: limit - 1] + "…"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
        return text if len(text) <= limit else text[: limit - 1] + "…"
    return value


def profile_payload(payload: Payload) -> Profile:
    """A deterministic description of the payload's shape."""
    if payload.kind == "text":
        text = str(payload.data)
        return Profile(
            kind="text", record_count=0, fields=[], records_path="", sample=[],
            text_preview=text[:1500],
        )
    if payload.kind == "csv":
        records, path = list(payload.data), ""
    else:
        records, path = _find_records(payload.data)
        if not records:
            if isinstance(payload.data, dict):
                # a single object: its keys are the "fields"
                obj = payload.data
                fields = [
                    FieldProfile(k, [_type_name(v)], [_short(v)], 1) for k, v in list(obj.items())[:60]
                ]
                return Profile(
                    kind="object", record_count=1, fields=fields, records_path="",
                    sample=[{k: _short(v) for k, v in list(obj.items())[:60]}],
                    top_level_keys=list(obj.keys())[:60],
                )
            return Profile(
                kind="scalar", record_count=0, fields=[], records_path="",
                sample=[_short(payload.data)], text_preview=str(payload.data)[:500],
            )

    fields: dict[str, FieldProfile] = {}
    for rec in records[:500]:
        if not isinstance(rec, dict):
            continue
        for key, value in rec.items():
            f = fields.get(key)
            if f is None:
                f = fields[key] = FieldProfile(key, [], [], 0)
            t = _type_name(value)
            if t not in f.types and t != "null":
                f.types.append(t)
            if value is not None and value != "":
                f.filled += 1
                if len(f.samples) < 3 and _short(value) not in f.samples:
                    f.samples.append(_short(value))
    top = list(payload.data.keys())[:30] if isinstance(payload.data, dict) else []
    sample = [
        {k: _short(v) for k, v in rec.items()} if isinstance(rec, dict) else _short(rec)
        for rec in records[:SAMPLE_RECORDS]
    ]
    return Profile(
        kind="records", record_count=len(records), fields=list(fields.values())[:80],
        records_path=path, sample=sample, top_level_keys=top,
    )


# ------------------------------------------------------- knowledge rendering


def render_as_text(payload: Payload, profile: Profile, *, title: str, url: str) -> str:
    """The payload as a document the knowledge plane can chunk and cite.

    One record per line, ``field: value`` pairs, so a question about a store
    or a product lands on the line that mentions it.
    """
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(payload.fetched_at))
    head = [f"{title}", f"Source: {url}", f"Fetched: {stamp}"]
    if profile.kind == "text":
        body = str(payload.data)[:MAX_DOC_CHARS]
        return "\n".join(head) + "\n\n" + body
    if profile.kind in ("object", "scalar"):
        body = json.dumps(payload.data, ensure_ascii=False, indent=1)[:MAX_DOC_CHARS]
        return "\n".join(head) + "\n\n" + body

    records = find_records(payload)
    head.append(f"Records: {len(records)}")
    lines = "\n".join(head) + "\n\n"
    for rec in records[:MAX_DOC_RECORDS]:
        if isinstance(rec, dict):
            line = "; ".join(f"{k}: {_flat(v)}" for k, v in rec.items() if v not in (None, ""))
        else:
            line = _flat(rec)
        lines += line + "\n"
        if len(lines) > MAX_DOC_CHARS:
            lines += "… (cut at the document size limit)\n"
            break
    return lines


def _flat(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
