"""Skill registry — the catalogue of safe, verified tools.

``visible_for`` returns only the skills a given principal may see and use,
combining tenant ownership, role, and data-class clearance. The orchestrator
offers exactly that subset to the model, so an unauthorized user is never even
*told* a privileged skill exists.
"""

from __future__ import annotations

from ..domain import Principal
from .base import Skill


class SkillRegistry:
    def __init__(self) -> None:
        # keyed by (tenant_id, name) so different tenants can define
        # same-named skills without collision.
        self._skills: dict[tuple[str, str], Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[(skill.tenant_id, skill.name)] = skill

    def unregister(self, tenant_id: str, name: str) -> bool:
        """Remove a skill from the live catalogue (edit/delete/disable).

        Returns whether anything was removed, so a rename that finds nothing to
        drop is not an error.
        """
        return self._skills.pop((tenant_id, name), None) is not None

    def get(self, tenant_id: str, name: str) -> Skill | None:
        """The registered skill under exactly this (tenant, name), or None."""
        return self._skills.get((tenant_id, name))

    def visible_for(self, principal: Principal) -> list[Skill]:
        return [s for s in self._skills.values() if s.visible_to(principal)]

    def resolve(self, principal: Principal, name: str) -> Skill | None:
        """Find a skill by name that this principal may use.

        Prefers a tenant-specific skill over a global one of the same name.
        Returns ``None`` if none is visible — the caller must treat this as
        "not found" without disclosing whether it exists but is forbidden.
        """
        candidates = [
            self._skills.get((principal.tenant_id, name)),
            self._skills.get(("*", name)),
        ]
        for skill in candidates:
            if skill is not None and skill.visible_to(principal):
                return skill
        return None
