"""Real, guarded data connectors for the skills data plane.

Skills wrap these to run *verified, read-only* queries against a company's
database or API. Guardrails (read-only enforcement, row limits, timeouts,
parameter binding) live here so every skill inherits them.
"""

from .sql import SqlConnector, ReadOnlyViolation
from .rest import RestConnector

__all__ = ["SqlConnector", "RestConnector", "ReadOnlyViolation"]
