"""Skills that let the assistant consult KARAG's own source code.

These are how "if the model isn't sure, it reads the current code" works. They
carry no tenant and no data class beyond ``PUBLIC``: source is not customer
data, and the deny-list in :mod:`.codebase` keeps credentials and runtime state
out of reach. Every user gets them, because every user may ask how the platform
works.
"""

from __future__ import annotations

from ..domain import DataClass, Principal
from ..skills.base import Skill, SkillResult
from .codebase import CodebaseIndex, PathNotAllowed
from .handbook import PLATFORM_DIGEST, guides_for


def platform_skills(index: CodebaseIndex) -> list[Skill]:
    """Read-only introspection tools over the running platform's own source."""

    async def _search(principal: Principal, args: dict) -> SkillResult:
        query = str(args["query"])
        subdir = str(args.get("subdir", "") or "")
        try:
            hits = index.search(query, subdir=subdir)
        except PathNotAllowed as exc:
            return SkillResult(
                data={"error": str(exc)}, query_shown=f"search {query!r} in {subdir!r}"
            )
        return SkillResult(
            data={
                "hits": [h.to_dict() for h in hits],
                "count": len(hits),
                "note": "Line numbers are current as of this call.",
            },
            query_shown=f"search_codebase(query={query!r}, subdir={subdir!r})",
        )

    async def _read(principal: Principal, args: dict) -> SkillResult:
        path = str(args["path"])
        try:
            body = (
                index.read_numbered(path)
                if args.get("with_line_numbers", True)
                else index.read(path)
            )
        except PathNotAllowed as exc:
            # Refusals are data, not exceptions: the model should say "that file
            # isn't readable" rather than the turn failing.
            return SkillResult(
                data={"error": str(exc)}, query_shown=f"read_source_file({path!r})"
            )
        return SkillResult(
            data={"path": path, "content": body},
            query_shown=f"read_source_file({path!r})",
        )

    async def _list(principal: Principal, args: dict) -> SkillResult:
        subdir = str(args.get("subdir", "") or "")
        try:
            files = index.files(subdir)
        except PathNotAllowed as exc:
            return SkillResult(data={"error": str(exc)}, query_shown="list_source_files")
        return SkillResult(
            data={"files": files, "count": len(files)},
            query_shown=f"list_source_files(subdir={subdir!r})",
        )

    async def _handbook(principal: Principal, args: dict) -> SkillResult:
        topic = str(args.get("topic", "") or "").strip().lower()
        guides = guides_for(principal)
        payload: dict = {
            "roles": list(principal.roles),
            "guides": {role: text for role, text in guides},
        }
        # The digest is already in the system prompt; resend it only when the
        # user explicitly asks for the overview, to avoid duplicating tokens.
        if not topic or topic in {"overview", "platform", "architecture", "all"}:
            payload["digest"] = PLATFORM_DIGEST
        return SkillResult(
            data=payload, query_shown=f"platform_handbook(topic={topic!r})"
        )

    return [
        Skill(
            name="search_codebase",
            description=(
                "Search KARAG's own source code for a regex or literal string. Use "
                "this when a question about how the platform behaves needs a fact "
                "the handbook does not state — then read the matching file. "
                "Returns path, line number and the matching line."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Regex or literal to find"},
                    "subdir": {
                        "type": "string",
                        "description": "Optional repo subdirectory to limit the search, e.g. 'karag/api'",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=_search,
            required_data_class=DataClass.PUBLIC,
            tenant_id="*",
        ),
        Skill(
            name="read_source_file",
            description=(
                "Read one of KARAG's own source files, with line numbers. Use after "
                "search_codebase to confirm exact behaviour before answering. Cite "
                "what you read as path:line. Secrets and databases are not readable."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repo-relative path, e.g. 'karag/rbac.py'",
                    },
                    "with_line_numbers": {"type": "boolean"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=_read,
            required_data_class=DataClass.PUBLIC,
            tenant_id="*",
        ),
        Skill(
            name="list_source_files",
            description=(
                "List KARAG's source files, optionally under one directory. Use to "
                "orient yourself before searching when you do not know where a "
                "feature lives."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "subdir": {"type": "string", "description": "Optional subdirectory"},
                },
                "required": [],
                "additionalProperties": False,
            },
            handler=_list,
            required_data_class=DataClass.PUBLIC,
            tenant_id="*",
        ),
        Skill(
            name="platform_handbook",
            description=(
                "Get KARAG's platform handbook and the capability guide for the "
                "asking user's roles. Use for 'how do I…', 'what can I do here', "
                "'show me around' and onboarding questions."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Optional focus, e.g. 'skills', 'overview', 'rbac'",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            handler=_handbook,
            required_data_class=DataClass.PUBLIC,
            tenant_id="*",
        ),
    ]
