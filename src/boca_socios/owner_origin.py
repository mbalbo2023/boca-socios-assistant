"""Canonical owner RP origin shared by the sealed, host and image gates."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit


def owner_rp_host(origin: str) -> str:
    """Allow DNS HTTPS origins or the one reviewed private tablet tunnel origin."""
    if not isinstance(origin, str):
        raise ValueError("invalid owner origin")
    try:
        parsed = urlsplit(origin)
        host, port = parsed.hostname, parsed.port
    except ValueError:
        raise ValueError("invalid owner origin") from None
    if (
        host is None
        or parsed.scheme != "https"
        or parsed.netloc != (host if port is None else f"{host}:{port}")
        or port == 443
        or (port is not None and not 1024 <= port <= 65535)
        or origin != f"https://{parsed.netloc}"
    ):
        raise ValueError("invalid owner origin")
    if host == "localhost":
        if port != 8443:
            raise ValueError("invalid owner origin")
        return host
    if (
        re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host) is None
        or len(host) > 253
        or host.endswith(".localhost")
        or any(
            len(label) > 63 or label.startswith("-") or label.endswith("-")
            for label in host.split(".")
        )
    ):
        raise ValueError("invalid owner origin")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    raise ValueError("invalid owner origin")
