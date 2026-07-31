"""The code-change workflow: propose → review → apply or discard.

Propose is the only step an AI turn can reach. Apply is a human action taken
against a stored proposal, and it re-checks the role rather than trusting that
whoever created the proposal is the one applying it.
"""

from __future__ import annotations

import re
import time

from ..audit import AuditEvent, AuditLog, NullAuditLog
from ..domain import Principal
from ..errors import KaragError
from ..request_context import untrusted_sources
from .guard import ENGINEER_ROLE, CodeChangeRefused, FileEdit, assert_may_edit
from .proposals import (
    APPLIED,
    DISCARDED,
    PENDING,
    Proposal,
    ProposalNotFound,
    ProposalStore,
    new_proposal_id,
)
from .workspace import GitWorkspace


def _slug(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:limit].rstrip("-") or "change")


class CodeChangeService:
    def __init__(
        self,
        workspace: GitWorkspace,
        store: ProposalStore,
        *,
        audit: AuditLog | None = None,
    ) -> None:
        self._ws = workspace
        self._store = store
        self._audit = audit or NullAuditLog()

    # ---- propose ---------------------------------------------------------

    def propose(
        self,
        principal: Principal,
        *,
        summary: str,
        edits: list[FileEdit],
        model: str = "",
        run_tests: bool = True,
    ) -> Proposal:
        """Validate, branch, commit, test — and store the result for review."""
        try:
            assert_may_edit(principal, edits, untrusted=untrusted_sources())
        except CodeChangeRefused as exc:
            self._log(principal, "code_propose", "deny",
                      {"reason": str(exc), "files": [e.path for e in edits]})
            raise

        branch = f"karag/ai-{time.strftime('%Y%m%d-%H%M%S')}-{_slug(summary)}"
        message = (
            f"{summary}\n\n"
            f"Proposed by KARAG's assistant on behalf of {principal.user_id} "
            f"({principal.tenant_id}) using {model or 'the configured model'}.\n"
            "Not reviewed by a human at commit time."
        )
        result = self._ws.propose(
            branch, [(e.path, e.content) for e in edits], message, run_tests=run_tests
        )

        proposal = Proposal(
            id=new_proposal_id(),
            tenant_id=principal.tenant_id,
            author=principal.user_id,
            summary=summary,
            branch=result.branch,
            diff=result.diff,
            files_changed=result.files_changed,
            insertions=result.insertions,
            deletions=result.deletions,
            tests_passed=bool(result.tests and result.tests.passed),
            tests_summary=result.tests.summary if result.tests else "not run",
            model=model,
        )
        self._store.create(proposal)
        self._log(principal, "code_propose", "allow", {
            "proposal": proposal.id, "branch": branch,
            "files": result.files_changed, "tests_passed": proposal.tests_passed,
        })
        return proposal

    # ---- review ----------------------------------------------------------

    def get(self, principal: Principal, proposal_id: str) -> Proposal:
        self._require_engineer(principal, "code_view", proposal_id)
        proposal = self._store.get(proposal_id)
        if proposal is None:
            raise ProposalNotFound(proposal_id)
        return proposal

    def list(self, principal: Principal, *, status: str | None = None) -> list[Proposal]:
        self._require_engineer(principal, "code_list", "")
        return self._store.list(status=status)

    def apply(self, principal: Principal, proposal_id: str) -> Proposal:
        """Merge a reviewed proposal. Human-triggered; the role is re-checked."""
        proposal = self.get(principal, proposal_id)
        if proposal.status != PENDING:
            raise KaragError(f"proposal is already {proposal.status}")
        try:
            self._ws.apply(proposal.branch)
        except KaragError as exc:
            self._log(principal, "code_apply", "deny",
                      {"proposal": proposal_id, "error": str(exc)})
            raise
        proposal.status = APPLIED
        proposal.resolved_at = time.time()
        proposal.resolved_by = principal.user_id
        self._store.update(proposal)
        self._log(principal, "code_apply", "allow",
                  {"proposal": proposal_id, "branch": proposal.branch,
                   "files": proposal.files_changed})
        return proposal

    def discard(self, principal: Principal, proposal_id: str) -> Proposal:
        proposal = self.get(principal, proposal_id)
        if proposal.status != PENDING:
            raise KaragError(f"proposal is already {proposal.status}")
        self._ws.discard(proposal.branch)
        proposal.status = DISCARDED
        proposal.resolved_at = time.time()
        proposal.resolved_by = principal.user_id
        self._store.update(proposal)
        self._log(principal, "code_discard", "allow", {"proposal": proposal_id})
        return proposal

    # ---- guards ----------------------------------------------------------

    def _require_engineer(self, principal: Principal, action: str, resource: str) -> None:
        if ENGINEER_ROLE not in principal.roles:
            self._log(principal, action, "deny", {"reason": "not_an_engineer"})
            raise CodeChangeRefused(
                "reviewing or applying code changes requires the karag_engineer role"
            )

    def _log(self, principal: Principal, action: str, decision: str, detail: dict) -> None:
        self._audit.record(AuditEvent(
            action=action, tenant_id=principal.tenant_id, user_id=principal.user_id,
            decision=decision, resource=detail.get("proposal", ""), detail=detail,
        ))
