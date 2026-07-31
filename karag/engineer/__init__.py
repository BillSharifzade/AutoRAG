"""Guarded self-modification: KARAG proposing changes to its own source.

The capability is deliberately narrow. An AI turn can only ever *propose*: the
change lands on a git branch with the test suite's verdict attached, and a human
applies or discards it. :mod:`.guard` holds every rule about who may propose,
which paths are permanently off-limits, and why a turn carrying untrusted
content is refused outright.
"""

from .guard import (
    ENGINEER_ROLE,
    PROTECTED_PATHS,
    CodeChangeRefused,
    FileEdit,
    assert_may_edit,
    is_protected,
)
from .proposals import (
    APPLIED,
    DISCARDED,
    PENDING,
    InMemoryProposalStore,
    Proposal,
    ProposalNotFound,
    ProposalStore,
    SqliteProposalStore,
)
from .service import CodeChangeService
from .skills import engineer_skills
from .workspace import GitError, GitWorkspace

__all__ = [
    "ENGINEER_ROLE",
    "PROTECTED_PATHS",
    "CodeChangeRefused",
    "FileEdit",
    "assert_may_edit",
    "is_protected",
    "APPLIED",
    "DISCARDED",
    "PENDING",
    "InMemoryProposalStore",
    "Proposal",
    "ProposalNotFound",
    "ProposalStore",
    "SqliteProposalStore",
    "CodeChangeService",
    "engineer_skills",
    "GitError",
    "GitWorkspace",
]
