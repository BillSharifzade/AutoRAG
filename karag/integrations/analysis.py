"""The model explains a data source to the person connecting it.

Both flows here hand the model a *deterministic* profile (what the platform
measured) and ask for a structured report through a tool call, so the answer
arrives as fields the UI can render rather than prose to be parsed. When no
model is available, or the model does not call the tool, a plain heuristic
report is produced from the same profile — the flow never dead-ends.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from ..llm.base import ChatMessage, Generator, MsgRole, ToolSpec
from .payload import Profile

LANGUAGE_NAMES = {"ru": "Russian", "en": "English", "tg": "Tajik"}

_SLUG_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ғ": "g", "ӣ": "i", "қ": "q", "ӯ": "u", "ҳ": "h", "ҷ": "j",
}


def slug(text: str, *, max_len: int = 40) -> str:
    """A snake_case identifier from anything a person types, Cyrillic included."""
    lowered = "".join(_SLUG_TRANSLIT.get(ch, ch) for ch in text.lower())
    out = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")[:max_len].strip("_")
    out = re.sub(r"^[0-9_]+", "", out)
    return out or "source"


def _language(code: str | None) -> str:
    return LANGUAGE_NAMES.get((code or "ru").lower(), "Russian")


# ---------------------------------------------------------------- payloads

_PAYLOAD_TOOL = ToolSpec(
    name="report_analysis",
    description="Report what this data source appears to be, for the person connecting it.",
    input_schema={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "2–4 plain sentences: what the data is, how many records, what each record represents, anything odd.",
            },
            "suggested_name": {"type": "string", "description": "A short human title for this source, 2–5 words."},
            "suggested_description": {
                "type": "string",
                "description": "One sentence an assistant selects this source by: when a question should use it.",
            },
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "meaning": {"type": "string", "description": "What the field means, in a few words."},
                    },
                    "required": ["name", "meaning"],
                },
            },
            "concerns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Things the person should check: empty fields, ambiguous units, missing ids, truncation.",
            },
            "looks_right": {"type": "boolean", "description": "Whether this looks like usable business data."},
        },
        "required": ["summary", "suggested_name", "suggested_description", "fields", "concerns", "looks_right"],
    },
)


def _payload_prompt(profile: Profile, url: str, comment: str, previous: dict | None) -> str:
    facts = {
        "url": url,
        "shape": profile.kind,
        "record_count": profile.record_count,
        "records_path": profile.records_path,
        "top_level_keys": profile.top_level_keys,
        "fields": [f.to_dict() for f in profile.fields],
        "sample_records": profile.sample[:5],
        "text_preview": profile.text_preview[:800],
    }
    parts = ["Measured profile of the data the endpoint returned:", json.dumps(facts, ensure_ascii=False, indent=1)]
    if previous:
        parts += ["\nYour previous report:", json.dumps(previous, ensure_ascii=False)]
    if comment:
        parts += ["\nThe person's comment or correction (treat as the truth about their business):", comment]
    parts.append("\nCall report_analysis exactly once.")
    return "\n".join(parts)


def _heuristic_payload(profile: Profile, url: str, language: str) -> dict:
    ru = language == "ru"
    host = urlsplit(url).hostname or url
    path = urlsplit(url).path.strip("/").split("/")
    last = next((p for p in reversed(path) if p and not p.isdigit()), host)
    fields = [f.name for f in profile.fields]
    if profile.kind == "records":
        summary = (
            f"Получено {profile.record_count} записей, поля: {', '.join(fields[:12])}."
            if ru else
            f"{profile.record_count} records with fields: {', '.join(fields[:12])}."
        )
    elif profile.kind == "object":
        summary = ("Один объект с полями: " if ru else "A single object with fields: ") + ", ".join(fields[:12])
    else:
        summary = "Текстовый ответ." if ru else "A text response."
    return {
        "summary": summary,
        "suggested_name": last.replace("-", " ").replace("_", " ").title()[:60],
        "suggested_description": (f"Данные с {host}: {last}" if ru else f"Data from {host}: {last}"),
        "fields": [
            {"name": f.name, "meaning": ("/".join(f.types) + (f" · " + str(f.samples[0]) if f.samples else ""))}
            for f in profile.fields[:40]
        ],
        "concerns": [] if profile.record_count or profile.kind != "records" else
        (["Записей не найдено." ] if ru else ["No records were found."]),
        "looks_right": bool(profile.fields) or profile.kind == "text",
        "source": "heuristic",
    }


def _normalise_report(args: dict, profile: Profile) -> dict:
    fields = []
    for f in args.get("fields") or []:
        if isinstance(f, dict) and f.get("name"):
            fields.append({"name": str(f["name"]), "meaning": str(f.get("meaning", ""))})
    known = {f.name for f in profile.fields}
    if known:
        fields = [f for f in fields if f["name"] in known] or fields
    return {
        "summary": str(args.get("summary", "")).strip(),
        "suggested_name": str(args.get("suggested_name", "")).strip()[:80],
        "suggested_description": str(args.get("suggested_description", "")).strip()[:300],
        "fields": fields,
        "concerns": [str(c) for c in (args.get("concerns") or []) if str(c).strip()][:8],
        "looks_right": bool(args.get("looks_right", True)),
        "source": "model",
    }


def _parse_json_report(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and "summary" in data else None


async def analyze_payload(
    generator: Generator | None,
    profile: Profile,
    *,
    url: str,
    language: str = "ru",
    comment: str = "",
    previous: dict | None = None,
) -> dict:
    """What the model makes of the payload, or a heuristic report without one."""
    if generator is None:
        return _heuristic_payload(profile, url, language)
    system = (
        "You help a non-technical employee connect a company data source to an "
        "assistant. You are shown a measured profile of what an HTTP endpoint "
        "returned. Explain in plain words what the data seems to be and what "
        "each field means, name it, and write the one sentence an assistant will "
        "use to decide when to consult this source. Do not invent fields that "
        f"are not in the profile. Write every text in {_language(language)}. "
        "Report by calling the report_analysis tool exactly once."
    )
    try:
        resp = await generator.generate(
            system=system,
            messages=[ChatMessage(role=MsgRole.USER, content=_payload_prompt(profile, url, comment, previous))],
            tools=[_PAYLOAD_TOOL],
        )
    except Exception:  # noqa: BLE001 — a provider outage must not block the flow
        return _heuristic_payload(profile, url, language)
    for call in resp.tool_calls:
        if call.name == _PAYLOAD_TOOL.name and isinstance(call.arguments, dict):
            return _normalise_report(call.arguments, profile)
    parsed = _parse_json_report(resp.text or "")
    if parsed:
        return _normalise_report(parsed, profile)
    report = _heuristic_payload(profile, url, language)
    if resp.text:
        report["summary"] = resp.text.strip()[:1200]
        report["source"] = "model_text"
    return report


# ----------------------------------------------------------------- schemas

_SCHEMA_TOOL = ToolSpec(
    name="report_schema",
    description="Describe a database for the person connecting it.",
    input_schema={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "2–4 plain sentences: what this database holds, which tables matter, obvious relations.",
            },
            "suggested_description": {
                "type": "string",
                "description": "One sentence an assistant selects this database by.",
            },
            "tables": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "meaning": {"type": "string", "description": "What one row of this table represents."},
                    },
                    "required": ["name", "meaning"],
                },
            },
            "concerns": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "suggested_description", "tables", "concerns"],
    },
)


def _schema_prompt(schema: dict, name: str, comment: str, previous: dict | None) -> str:
    compact = {
        "name": name,
        "backend": schema.get("backend"),
        "table_count": schema.get("table_count"),
        "tables": [
            {
                "name": t["name"],
                "kind": t.get("kind"),
                "rows": t.get("row_estimate"),
                "columns": [f"{c['name']} {c.get('type', '')}".strip() for c in t["columns"][:40]],
                "sample": t.get("sample", [])[:2],
            }
            for t in schema.get("tables", [])[:60]
        ],
    }
    parts = ["Schema read from the database (read-only):", json.dumps(compact, ensure_ascii=False, indent=1)]
    if previous:
        parts += ["\nYour previous report:", json.dumps(previous, ensure_ascii=False)]
    if comment:
        parts += ["\nThe person's comment or correction (treat as the truth about their business):", comment]
    parts.append("\nCall report_schema exactly once.")
    return "\n".join(parts)


def _heuristic_schema(schema: dict, name: str, language: str) -> dict:
    ru = language == "ru"
    tables = schema.get("tables", [])
    names = [t["name"] for t in tables]
    summary = (
        f"База «{name}»: {schema.get('table_count', len(tables))} таблиц — {', '.join(names[:15])}."
        if ru else
        f"Database '{name}': {schema.get('table_count', len(tables))} tables — {', '.join(names[:15])}."
    )
    return {
        "summary": summary,
        "suggested_description": (f"Данные из базы {name}" if ru else f"Data from the {name} database"),
        "tables": [
            {"name": t["name"], "meaning": ", ".join(c["name"] for c in t["columns"][:8])} for t in tables[:60]
        ],
        "concerns": [],
        "source": "heuristic",
    }


async def describe_schema(
    generator: Generator | None,
    schema: dict,
    *,
    name: str,
    language: str = "ru",
    comment: str = "",
    previous: dict | None = None,
) -> dict:
    if generator is None:
        return _heuristic_schema(schema, name, language)
    system = (
        "You help a non-technical employee connect a company database to an "
        "assistant. You are shown its tables, columns and a couple of sample rows. "
        "Explain in plain words what the database holds and what each table "
        "represents, and write the one sentence an assistant will use to decide "
        f"when to query it. Write every text in {_language(language)}. "
        "Report by calling the report_schema tool exactly once."
    )
    try:
        resp = await generator.generate(
            system=system,
            messages=[ChatMessage(role=MsgRole.USER, content=_schema_prompt(schema, name, comment, previous))],
            tools=[_SCHEMA_TOOL],
        )
    except Exception:  # noqa: BLE001
        return _heuristic_schema(schema, name, language)
    known = {t["name"] for t in schema.get("tables", [])}
    for call in resp.tool_calls:
        if call.name == _SCHEMA_TOOL.name and isinstance(call.arguments, dict):
            args = call.arguments
            tables = [
                {"name": str(t["name"]), "meaning": str(t.get("meaning", ""))}
                for t in (args.get("tables") or [])
                if isinstance(t, dict) and t.get("name") in known
            ]
            return {
                "summary": str(args.get("summary", "")).strip(),
                "suggested_description": str(args.get("suggested_description", "")).strip()[:300],
                "tables": tables,
                "concerns": [str(c) for c in (args.get("concerns") or [])][:8],
                "source": "model",
            }
    report = _heuristic_schema(schema, name, language)
    if resp.text:
        report["summary"] = resp.text.strip()[:1200]
        report["source"] = "model_text"
    return report
