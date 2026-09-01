"""What the platform is allowed to reach on the open internet.

Letting a model fetch a URL is the one capability that points *outward*, and it
carries a specific hazard the rest of KARAG does not have: the URL may be chosen
by the model, and the model's choice may have been shaped by text someone else
wrote. So a URL is not fetched because it looks fine — it is fetched only after
this module says so.

What is refused, and why:

* **Anything but http/https.** ``file://`` reads the server's disk;
  ``gopher://`` and friends are classic request-smuggling vectors.
* **Any address that resolves inside the perimeter.** Loopback, RFC1918,
  link-local (which is where every cloud provider parks its credential
  endpoint at ``169.254.169.254``), unique-local IPv6, and the rest. Every
  address a hostname resolves to must be public — one private answer is
  enough to refuse, because DNS may return several and a round-robin would
  otherwise be a coin flip.
* **Every redirect hop, re-checked.** A public URL that 302s to
  ``127.0.0.1`` is the standard way around a naive allow-list, so redirects
  are followed by hand rather than by the HTTP client.
* **Anything the operator did not allow.** With ``KARAG_WEB_ALLOW_HOSTS`` set,
  only those hosts (and their subdomains) are reachable at all.

None of this makes fetched content trustworthy — it only bounds where the
platform can be pointed. The content itself is marked untrusted by the skills
that use it.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..errors import KaragError

# Generous enough for a long article, small enough that one page cannot be used
# to exhaust memory or flood the model's context.
MAX_PAGE_BYTES = 2_000_000

# Only formats that are actually readable as text. A PDF or an image fetched
# from the open web is a file, not a source — the knowledge plane is where
# documents belong.
READABLE_TYPES = ("text/html", "text/plain", "application/json", "text/markdown",
                  "application/xhtml+xml", "text/xml", "application/xml")


class WebAccessDenied(KaragError):
    """The platform refused to reach this URL."""


@dataclass(frozen=True)
class WebPolicy:
    """Where this deployment may go. Empty allow-list means 'anywhere public'."""

    allow_hosts: tuple[str, ...] = ()
    deny_hosts: tuple[str, ...] = ()
    max_bytes: int = MAX_PAGE_BYTES
    timeout_s: float = 12.0
    max_redirects: int = 4
    # Off by default: resolving names is what stops a public hostname from
    # pointing at an internal address, and only an operator running an
    # air-gapped resolver has a reason to skip it.
    allow_private_addresses: bool = False

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "WebPolicy":
        import os

        e = env if env is not None else dict(os.environ)

        def hosts(name: str) -> tuple[str, ...]:
            raw = e.get(name, "")
            return tuple(h.strip().lower() for h in raw.split(",") if h.strip())

        return cls(
            allow_hosts=hosts("KARAG_WEB_ALLOW_HOSTS"),
            deny_hosts=hosts("KARAG_WEB_DENY_HOSTS"),
            max_bytes=int(e.get("KARAG_WEB_MAX_BYTES", str(MAX_PAGE_BYTES))),
            timeout_s=float(e.get("KARAG_WEB_TIMEOUT", "12")),
        )


def _host_matches(host: str, pattern: str) -> bool:
    """``example.com`` covers ``example.com`` and ``docs.example.com``."""
    return host == pattern or host.endswith(f".{pattern}")


def _resolved_addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Every address this name answers with, as parsed IPs."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise WebAccessDenied(f"could not resolve {host!r}") from exc
    out = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(info[4][0]))
        except ValueError:  # pragma: no cover — getaddrinfo returned a non-IP
            continue
    if not out:
        raise WebAccessDenied(f"could not resolve {host!r}")
    return out


def _is_public(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Reject everything that is not a routable, public unicast address.

    ``is_global`` alone is close but leaves gaps across versions, so the
    specific categories that matter for SSRF are named explicitly.
    """
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    ):
        return False
    # An IPv4 address wrapped in IPv6 (::ffff:127.0.0.1) must be judged as the
    # IPv4 address it really is.
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        return _is_public(mapped)
    return True


def check_url(url: str, policy: WebPolicy) -> str:
    """Return the URL if the platform may fetch it; raise otherwise.

    Called for the initial URL *and* for every redirect target.
    """
    parts = urlsplit(url.strip())

    if parts.scheme not in ("http", "https"):
        raise WebAccessDenied(
            f"{parts.scheme or 'that'} addresses are not reachable — http(s) only"
        )
    host = (parts.hostname or "").lower()
    if not host:
        raise WebAccessDenied("that URL has no host")

    if any(_host_matches(host, d) for d in policy.deny_hosts):
        raise WebAccessDenied(f"{host} is on this deployment's blocked list")
    if policy.allow_hosts and not any(
        _host_matches(host, a) for a in policy.allow_hosts
    ):
        raise WebAccessDenied(
            f"{host} is not on this deployment's allowed list of sites"
        )

    if not policy.allow_private_addresses:
        for addr in _resolved_addresses(host):
            if not _is_public(addr):
                # Deliberately vague about *which* address: the refusal should
                # not double as a map of the internal network.
                raise WebAccessDenied(
                    f"{host} points inside the private network and cannot be read"
                )
    return url


def readable_content_type(content_type: str) -> bool:
    base = content_type.split(";", 1)[0].strip().lower()
    return base in READABLE_TYPES
