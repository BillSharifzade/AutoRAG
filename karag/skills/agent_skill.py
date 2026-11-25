"""Agent Skills — procedural knowledge, disclosed in three levels.

A *lookup* skill (``sql`` / ``rest``) answers "what is the number". An **agent
skill** answers "how do we do this here": the company's own written procedure
for writing a weekly report, handling a refund, onboarding a supplier. It is
Anthropic's Agent Skill format — a ``SKILL.md`` — stored as data rather than as
a folder on disk, with the same progressive disclosure:

* **Level 1 — metadata.** ``name`` + ``description`` only. This is all that is
  ever pre-loaded: the skill is offered to the model as a tool whose description
  *is* the author's description, so a tenant can hold dozens of skills for
  roughly a hundred tokens each.
* **Level 2 — instructions.** The markdown body. It enters the context window
  only when the model calls the tool, which is the moment Claude would have run
  ``cat SKILL.md``.
* **Level 3 — bundled files.** Reference material the body points at
  (``reference/finance.md``, a schema, a template). Each is fetched by a second
  call naming the file, so files the task doesn't need cost nothing.

The rules from the published format are enforced here at authoring time rather
than discovered at ask time: hyphen-case name within 64 characters, a non-empty
description within 1024, no XML tags in either, and no reserved word.

Instructions are *content*, not privilege. An agent skill grants no data access:
it is visible under the same RBAC as every other skill, it cannot widen the
principal's clearance, and its text is marked as content KARAG did not author so
the code-change guard refuses a turn that read one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..domain import DataClass, Principal
from ..errors import ValidationError
from ..request_context import mark_untrusted_content
from .base import Skill, SkillResult

# Published format limits — see Anthropic's "Skill authoring best practices".
MAX_NAME = 64
MAX_DESCRIPTION = 1024
# Advisory, not enforced: the guidance is to split a body past ~500 lines into
# bundled files. The authoring UI coaches on it; a long skill still works.
ADVISED_MAX_BODY_LINES = 500

MAX_RESOURCES = 32
MAX_RESOURCE_PATH = 128

_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_RESERVED_WORDS = ("anthropic", "claude")
_XMLISH = re.compile(r"<[/a-zA-Z!]")
_RESOURCE_PATH_RE = re.compile(r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*")


@dataclass(frozen=True)
class SkillResource:
    """One bundled file — level 3, read only when the instructions point at it."""

    path: str
    content: str

    def to_dict(self) -> dict:
        return {"path": self.path, "content": self.content}

    @staticmethod
    def from_dict(d: dict) -> "SkillResource":
        return SkillResource(path=str(d.get("path", "")), content=str(d.get("content", "")))


# ---- validation ---------------------------------------------------------


def validate_name(name: str) -> None:
    if not name:
        raise ValidationError("a skill needs a name")
    if len(name) > MAX_NAME:
        raise ValidationError(f"name must be {MAX_NAME} characters or fewer")
    if not _NAME_RE.fullmatch(name):
        raise ValidationError(
            "name must be lowercase letters, numbers and hyphens only "
            "(for example: writing-weekly-reports)"
        )
    for word in _RESERVED_WORDS:
        if word in name:
            raise ValidationError(f"name must not contain the reserved word {word!r}")


def validate_description(description: str) -> None:
    text = description.strip()
    if not text:
        # The description is the whole of level 1: with nothing here the model
        # has no basis on which to pick the skill, so it would never fire.
        raise ValidationError(
            "a description is required — it is the only thing the assistant sees "
            "before deciding to use this skill"
        )
    if len(text) > MAX_DESCRIPTION:
        raise ValidationError(
            f"description must be {MAX_DESCRIPTION} characters or fewer"
        )
    if _XMLISH.search(text):
        raise ValidationError("description must not contain XML tags")


def validate_resources(resources: tuple[SkillResource, ...]) -> None:
    if len(resources) > MAX_RESOURCES:
        raise ValidationError(f"a skill may bundle at most {MAX_RESOURCES} files")
    seen: set[str] = set()
    for res in resources:
        path = res.path.strip()
        if not path:
            raise ValidationError("every bundled file needs a name")
        if len(path) > MAX_RESOURCE_PATH:
            raise ValidationError(
                f"file path {path!r} is longer than {MAX_RESOURCE_PATH} characters"
            )
        if path.startswith("/") or "\\" in path:
            raise ValidationError(
                f"file path {path!r} must be relative and use forward slashes"
            )
        if not _RESOURCE_PATH_RE.fullmatch(path) or ".." in path.split("/"):
            raise ValidationError(f"file path {path!r} is not a valid relative path")
        if path in seen:
            raise ValidationError(f"two bundled files are both named {path!r}")
        seen.add(path)


def validate_agent_skill(
    *, name: str, description: str, instructions: str, resources: tuple[SkillResource, ...]
) -> None:
    """Everything the published format requires, checked before the skill stores."""
    validate_name(name)
    validate_description(description)
    if not instructions.strip():
        raise ValidationError(
            "instructions are required — this is what the assistant reads once "
            "the skill is triggered"
        )
    if _XMLISH.search(name):
        raise ValidationError("name must not contain XML tags")
    validate_resources(resources)


# ---- SKILL.md interchange ----------------------------------------------


def render_skill_md(name: str, description: str, instructions: str) -> str:
    """The skill as a real ``SKILL.md``.

    Same bytes Claude Code or claude.ai would read, so a procedure written here
    is portable out of KARAG rather than trapped in its database.
    """
    body = instructions.strip("\n")
    return f"---\nname: {name}\ndescription: {description.strip()}\n---\n\n{body}\n"


_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)


def parse_skill_md(text: str) -> tuple[str, str, str]:
    """Split a pasted ``SKILL.md`` into ``(name, description, body)``.

    Only the two required keys are read. A YAML value may be folded across
    continuation lines, which is how a long description is usually written.
    """
    match = _FRONTMATTER.match(text.lstrip("﻿").lstrip())
    if match is None:
        raise ValidationError(
            "that doesn't look like a SKILL.md — it needs a --- front-matter "
            "block with name and description"
        )
    front, body = match.group(1), match.group(2)

    fields: dict[str, str] = {}
    key: str | None = None
    for raw in front.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        header = re.match(r"([A-Za-z_][\w-]*)\s*:\s*(.*)$", raw)
        if header and not raw.startswith((" ", "\t")):
            key = header.group(1).lower()
            fields[key] = header.group(2).strip()
        elif key is not None:
            # folded continuation of the previous value
            fields[key] = f"{fields[key]} {raw.strip()}".strip()

    name = _unquote(fields.get("name", ""))
    description = _unquote(fields.get("description", ""))
    if not name or not description:
        raise ValidationError("SKILL.md front-matter must set both name and description")
    return name, description, body.strip("\n")


def _unquote(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


# ---- materialisation ----------------------------------------------------

_OPEN_SCHEMA = {
    "type": "object",
    "properties": {
        "file": {
            "type": "string",
            "description": (
                "Optional. The bundled file to open, exactly as named in the "
                "skill's instructions. Omit on the first call to read the "
                "instructions themselves."
            ),
        }
    },
    "required": [],
    "additionalProperties": False,
}


def make_agent_skill(
    *,
    name: str,
    description: str,
    instructions: str,
    resources: tuple[SkillResource, ...] = (),
    required_data_class: DataClass = DataClass.OPERATIONAL,
    required_roles: frozenset[str] = frozenset(),
    tenant_id: str = "*",
) -> Skill:
    """Turn a stored agent skill into the tool the model may call.

    The tool's description is the author's description verbatim — level 1 is
    exactly what was written, because that is what the model matches a request
    against.
    """
    by_path = {r.path: r.content for r in resources}
    listing = sorted(by_path)

    async def handler(principal: Principal, args: dict) -> SkillResult:
        # Instructions are authored inside the tenant, but they are still text a
        # human wrote into a database — never grounds for rewriting the platform.
        mark_untrusted_content("skill instructions")

        wanted = str(args.get("file") or "").strip()
        if not wanted:
            return SkillResult(
                data={
                    "skill": name,
                    "instructions": instructions,
                    "bundled_files": listing,
                },
                query_shown=f"open_skill({name!r})",
            )
        if wanted not in by_path:
            return SkillResult(
                data={
                    "skill": name,
                    "error": "no_such_file",
                    "bundled_files": listing,
                },
                query_shown=f"open_skill({name!r}, file={wanted!r})",
            )
        return SkillResult(
            data={"skill": name, "file": wanted, "content": by_path[wanted]},
            query_shown=f"open_skill({name!r}, file={wanted!r})",
        )

    return Skill(
        category="procedure",
        name=name,
        description=description,
        input_schema=_OPEN_SCHEMA,
        handler=handler,
        required_data_class=required_data_class,
        required_roles=required_roles,
        tenant_id=tenant_id,
    )
