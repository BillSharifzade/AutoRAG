"""JWT (HS256) authentication — stdlib only, no external dependency.

Verifies the signature and expiry of a bearer token and maps its claims to a
:class:`~karag.domain.Principal`. This is the real-auth path an SSO/IdP plugs
into: the IdP issues signed JWTs with ``tenant``, ``sub`` and ``roles`` claims;
KARAG verifies them here. Claims are the source of tenant + roles, so a token
can never grant access to another tenant it wasn't issued for.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from ..domain import Principal
from ..errors import AccessDenied


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(seg: str) -> bytes:
    pad = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad)


def issue_jwt(secret: str, claims: dict, *, ttl_seconds: int = 3600) -> str:
    """Helper to mint a token (an IdP would normally do this)."""
    header = {"alg": "HS256", "typ": "JWT"}
    body = dict(claims)
    body.setdefault("iat", int(time.time()))
    body.setdefault("exp", int(time.time()) + ttl_seconds)
    seg = _b64url_encode(json.dumps(header, separators=(",", ":")).encode()) + "." + \
        _b64url_encode(json.dumps(body, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), seg.encode(), hashlib.sha256).digest()
    return f"{seg}.{_b64url_encode(sig)}"


class JwtResolver:
    def __init__(self, secret: str, *, leeway_seconds: int = 0) -> None:
        if not secret:
            raise ValueError("JWT secret must not be empty")
        self._secret = secret
        self._leeway = leeway_seconds

    def resolve(self, token: str) -> Principal:
        try:
            header_seg, body_seg, sig_seg = token.split(".")
        except ValueError as exc:
            raise AccessDenied("malformed token") from exc

        signing_input = f"{header_seg}.{body_seg}"
        expected = hmac.new(
            self._secret.encode(), signing_input.encode(), hashlib.sha256
        ).digest()
        try:
            provided = _b64url_decode(sig_seg)
        except Exception as exc:  # noqa: BLE001
            raise AccessDenied("bad signature encoding") from exc
        # constant-time comparison
        if not hmac.compare_digest(expected, provided):
            raise AccessDenied("bad signature")

        try:
            claims = json.loads(_b64url_decode(body_seg))
        except Exception as exc:  # noqa: BLE001
            raise AccessDenied("bad claims") from exc

        exp = claims.get("exp")
        if exp is not None and time.time() > float(exp) + self._leeway:
            raise AccessDenied("token expired")

        tenant = claims.get("tenant")
        user = claims.get("sub")
        roles = claims.get("roles", [])
        if not tenant or not user:
            raise AccessDenied("token missing tenant/sub")
        if isinstance(roles, str):
            roles = [r for r in roles.split() if r]
        return Principal(tenant_id=str(tenant), user_id=str(user), roles=tuple(roles))
