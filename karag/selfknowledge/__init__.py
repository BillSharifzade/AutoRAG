"""KARAG's knowledge of itself: its own source, and how to explain itself.

Two halves:

* :mod:`.codebase` + :mod:`.skills` — a guarded read-only window onto the
  repository, so the assistant can answer implementation questions from the
  *current* code instead of a stale summary.
* :mod:`.handbook` — a short hand-written digest of the platform's shape and a
  capability guide per role, carried in the system prompt.
"""

from .codebase import CodebaseIndex, PathNotAllowed
from .handbook import (
    PLATFORM_DIGEST,
    ROLE_GUIDES,
    guides_for,
    onboarding_prompt,
    system_context,
)
from .skills import platform_skills

__all__ = [
    "CodebaseIndex",
    "PathNotAllowed",
    "PLATFORM_DIGEST",
    "ROLE_GUIDES",
    "guides_for",
    "onboarding_prompt",
    "system_context",
    "platform_skills",
]
