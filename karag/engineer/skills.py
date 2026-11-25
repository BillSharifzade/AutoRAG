"""The one skill that can change KARAG's source — behind every guard.

The model supplies each file's complete new contents; verified code writes them
on a branch, runs the suite and produces a diff. That mirrors how the Office
authoring skills work: the model composes content, trusted code turns it into an
artefact, and the artefact is inspected before anyone relies on it.
"""

from __future__ import annotations

from ..domain import DataClass, Principal
from ..errors import KaragError
from ..skills.base import Skill, SkillResult
from .guard import ENGINEER_ROLE, MAX_FILES_PER_CHANGE, CodeChangeRefused, FileEdit
from .service import CodeChangeService


def engineer_skills(service: CodeChangeService) -> list[Skill]:
    async def _propose(principal: Principal, args: dict) -> SkillResult:
        summary = str(args["summary"]).strip()
        raw_files = args.get("files") or []
        if not isinstance(raw_files, list):
            raise KaragError("files must be a list of {path, content} objects")

        edits: list[FileEdit] = []
        for item in raw_files:
            if not isinstance(item, dict) or "path" not in item or "content" not in item:
                raise KaragError("each file needs a 'path' and a 'content'")
            edits.append(FileEdit(path=str(item["path"]), content=str(item["content"])))

        try:
            proposal = service.propose(
                principal, summary=summary, edits=edits,
                model=str(args.get("model", "")),
            )
        except CodeChangeRefused as exc:
            # A refusal is an answer, not a crash: the model should relay the
            # reason to the engineer rather than the turn erroring out.
            return SkillResult(
                data={"status": "refused", "reason": str(exc)},
                query_shown=f"propose_code_change({summary!r}) — refused",
            )

        return SkillResult(
            data={
                "status": "proposed",
                "proposal_id": proposal.id,
                "branch": proposal.branch,
                "files_changed": proposal.files_changed,
                "insertions": proposal.insertions,
                "deletions": proposal.deletions,
                "tests_passed": proposal.tests_passed,
                "tests_summary": proposal.tests_summary,
                "next_step": (
                    "Nothing is live. A human reviews the diff on the Engineering "
                    "page and applies or discards it."
                ),
            },
            query_shown=(
                f"propose_code_change({summary!r}) -> {proposal.branch} "
                f"(+{proposal.insertions} −{proposal.deletions})"
            ),
        )

    return [
        Skill(
            category="engineer",
            name="propose_code_change",
            description=(
                "Propose a change to KARAG's own source code. Supply the COMPLETE new "
                "contents of each file you are changing — read the file first with "
                "read_source_file so you preserve everything you are not changing. "
                "The change is committed to a new git branch and the full test suite "
                "runs against it; nothing goes live until a human applies it. "
                f"At most {MAX_FILES_PER_CHANGE} files. Access-control, identity and "
                "guard files are protected and will be refused. Requires the "
                f"{ENGINEER_ROLE} role."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "One line describing the change, used as the commit message and branch name",
                    },
                    "files": {
                        "type": "array",
                        "description": "Objects of {path, content} — content is the file's full new text",
                    },
                    "model": {
                        "type": "string",
                        "description": "The model authoring this change, for the audit record",
                    },
                },
                "required": ["summary", "files"],
                "additionalProperties": False,
            },
            handler=_propose,
            required_data_class=DataClass.PUBLIC,
            required_roles=frozenset({ENGINEER_ROLE}),
            tenant_id="*",
        ),
    ]
