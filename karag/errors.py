"""Typed errors for KARAG. Callers should catch these, never string-match."""

from __future__ import annotations


class KaragError(Exception):
    """Base class for all KARAG errors."""


class ConfigError(KaragError):
    """Invalid or missing configuration."""


class AccessDenied(KaragError):
    """The principal is not permitted to perform this action or see this data."""


class TenantIsolationError(KaragError):
    """A cross-tenant access was attempted — always a hard failure."""


class NotFoundError(KaragError):
    """A resource does not exist *within the caller's tenant*.

    Cross-tenant lookups raise this rather than a distinct error, so "belongs to
    another company" is indistinguishable from "does not exist".
    """


class SkillNotFound(KaragError):
    """Requested skill does not exist *for this principal*.

    Note: we intentionally do not distinguish "does not exist" from
    "exists but you may not use it" — revealing the difference leaks the
    catalogue of privileged skills to unauthorized users.
    """


class ValidationError(KaragError):
    """Tool/skill arguments failed schema validation."""


class GenerationError(KaragError):
    """The underlying LLM provider failed."""
