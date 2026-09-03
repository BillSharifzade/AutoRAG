"""Secrets at rest.

Connector credentials (a database password, a DSN) have to be stored somewhere
the server can read them back, and "somewhere" is the application database.
With ``KARAG_SECRET_KEY`` set they are sealed with Fernet (AES-CBC + HMAC via
the ``cryptography`` package) before they hit disk and unsealed only at
connection time; without a key they are stored as typed, which is what the
platform did before and what a single-machine install may accept.

The seal is marked with an ``enc:`` prefix so a value can always be told apart
from a plain one or an ``env:NAME`` pointer, and so a database written with a
key still reads correctly after the key is configured later.
"""

from __future__ import annotations

import base64
import hashlib
import os

from .errors import KaragError

PREFIX = "enc:"


def _fernet():
    key = os.environ.get("KARAG_SECRET_KEY", "")
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise KaragError(
            "KARAG_SECRET_KEY is set but the cryptography package is missing: "
            "pip install cryptography"
        ) from exc
    # Any passphrase works: it is stretched to the 32 bytes Fernet needs.
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def sealing_enabled() -> bool:
    return bool(os.environ.get("KARAG_SECRET_KEY"))


def seal(value: str) -> str:
    """Encrypt a secret for storage. Pointers (``env:``) and sealed values pass through."""
    if not isinstance(value, str) or not value:
        return value
    if value.startswith((PREFIX, "env:")):
        return value
    f = _fernet()
    if f is None:
        return value
    return PREFIX + f.encrypt(value.encode("utf-8")).decode("ascii")


def unseal(value: str) -> str:
    """Decrypt a stored secret. A plain value is returned unchanged."""
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    f = _fernet()
    if f is None:
        raise KaragError(
            "a stored secret is encrypted but KARAG_SECRET_KEY is not set"
        )
    try:
        return f.decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except Exception as exc:  # InvalidToken and friends
        raise KaragError("a stored secret could not be decrypted with this KARAG_SECRET_KEY") from exc
