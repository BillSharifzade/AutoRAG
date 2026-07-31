"""Role-based access control — the security core of KARAG.

The single most important rule (from the concept doc): access is enforced at
*retrieval time*, not by post-filtering the model's answer. This module only
decides *which data classes a principal may see*; the vector store and skill
executor are responsible for applying that decision before any content reaches
the model's context.

The matrix is deliberately explicit and default-deny:
  * A role grants exactly the classes listed for it — nothing implicit.
  * An unknown role contributes nothing.
  * A principal with no known roles sees nothing (fail-closed).
"""

from __future__ import annotations

from .domain import DataClass, Principal

DC = DataClass

# role name -> the set of data classes that role may read.
# Keep this table auditable: every grant is visible here, one row per role.
ROLE_DATA_CLASSES: dict[str, frozenset[DataClass]] = {
    "public": frozenset({DC.PUBLIC}),
    "employee": frozenset({DC.PUBLIC, DC.OPERATIONAL}),
    "hr": frozenset({DC.PUBLIC, DC.OPERATIONAL, DC.HR}),
    "finance": frozenset({DC.PUBLIC, DC.OPERATIONAL, DC.FINANCIAL}),
    "legal": frozenset({DC.PUBLIC, DC.OPERATIONAL, DC.REGULATED}),
    "qa": frozenset({DC.PUBLIC, DC.OPERATIONAL, DC.REGULATED}),
    # The doc's "technical staff": builds connectors and skills. Authoring is a
    # separate permission (see karag.skills.catalog.AUTHOR_ROLES); this row only
    # says what they may *read*, and a skill may never expose a class its author
    # is not cleared for.
    "skill_author": frozenset({DC.PUBLIC, DC.OPERATIONAL}),
    # KIT's platform operator: onboards and suspends tenants. Deliberately gets
    # no business data — running the platform is not a reason to read a
    # customer's financials, and §7's "never" has to hold for operators too.
    "platform_admin": frozenset({DC.PUBLIC}),
    # KIT's engineer: may propose changes to KARAG's own source (reviewed by a
    # human before anything lands). Like platform_admin, no business data —
    # working on the platform is not a reason to read what runs on it.
    "karag_engineer": frozenset({DC.PUBLIC}),
    # CEO / superadmin of *their own tenant* — never another tenant's data.
    "ceo": frozenset(
        {DC.PUBLIC, DC.OPERATIONAL, DC.HR, DC.FINANCIAL, DC.REGULATED}
    ),
    "admin": frozenset(
        {DC.PUBLIC, DC.OPERATIONAL, DC.HR, DC.FINANCIAL, DC.REGULATED}
    ),
}

# Roles permitted to add documents to the knowledge plane.
INGEST_ROLES: frozenset[str] = frozenset({"admin", "uploader", "ceo"})


def visible_classes(principal: Principal) -> frozenset[DataClass]:
    """Union of the data classes every one of the principal's roles grants.

    Returns an empty set (see nothing) if the principal has no known role.
    """
    allowed: set[DataClass] = set()
    for role in principal.roles:
        allowed |= ROLE_DATA_CLASSES.get(role, frozenset())
    return frozenset(allowed)


def can_access(principal: Principal, data_class: DataClass) -> bool:
    """Whether the principal may read content of ``data_class``."""
    return data_class in visible_classes(principal)


def can_ingest(principal: Principal, data_class: DataClass) -> bool:
    """Whether the principal may add a document of ``data_class``.

    Must hold an ingest role *and* be cleared for the class they are assigning
    — you cannot upload into a class you are not allowed to read.
    """
    if not principal.has_any_role(INGEST_ROLES):
        return False
    return can_access(principal, data_class)
