"""Security helpers for untrusted URLs."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

_BLOCKED_PUBLIC_FETCH_HOSTS = {
    "localhost",
    "metadata.google.internal",
}
_BLOCKED_PUBLIC_FETCH_SUFFIXES = (
    ".localhost",
    ".internal",
    ".local",
    ".lan",
)


def _is_non_public_ip(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not address.is_global


def normalize_public_http_url(url: str) -> str:
    """Normalize a URL or reject targets that are not clearly public HTTP(S)."""
    candidate = str(url or "").strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    try:
        parsed = urlsplit(candidate)
        host = (parsed.hostname or "").lower().rstrip(".")
        _ = parsed.port
    except (TypeError, ValueError):
        raise ValueError("only public HTTP(S) URLs are allowed") from None

    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or host in _BLOCKED_PUBLIC_FETCH_HOSTS
        or host.endswith(_BLOCKED_PUBLIC_FETCH_SUFFIXES)
        or _is_non_public_ip(host)
    ):
        raise ValueError("only public HTTP(S) URLs are allowed")

    return parsed.geturl()


def domain_matches(host: str, *domains: str) -> bool:
    """Match a hostname/cookie domain exactly or as a real subdomain."""
    normalized_host = str(host or "").lower().lstrip(".").rstrip(".")
    if not normalized_host:
        return False
    for domain in domains:
        allowed = domain.lower().lstrip(".").rstrip(".")
        if normalized_host == allowed or normalized_host.endswith("." + allowed):
            return True
    return False


def host_matches(url: str, *domains: str) -> bool:
    """Return whether *url* has an exact allowed host or a real subdomain.

    Only HTTP(S) URLs without userinfo are accepted. Using ``hostname`` rather
    than substring matching prevents lookalikes such as ``x.com.evil.test`` and
    userinfo disguises such as ``x.com@evil.test``.
    """
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        # ``hostname`` is permissive: malformed or out-of-range ports only
        # raise when ``port`` is accessed. Force that validation here so
        # hostile authorities fail closed.
        _ = parsed.port
    except (TypeError, ValueError):
        return False

    if parsed.scheme.lower() not in {"http", "https"}:
        return False
    if not host or parsed.username is not None or parsed.password is not None:
        return False

    return domain_matches(host, *domains)
