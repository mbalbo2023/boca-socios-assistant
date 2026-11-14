"""One worker-only login exchange using the recovered historical HTTP contract.

Contract evidence (not a claim about the current provider):
https://github.com/pany100/bocasociosv2/blob/f107a88dba195fead329616529fa074df33be083/constants.js
https://github.com/pany100/bocasociosv2/blob/f107a88dba195fead329616529fa074df33be083/login.js

Original implementation; none of the source's TLS disabling, Queue-it setup,
fingerprint headers, retries or logging is copied. The caller must supply the
existing authorized worker session. A protocol alone cannot establish that
provenance, its lifecycle authorization or its host network ownership.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from time import time
from typing import Protocol

from boca_socios.browser.worker_health import validate_worker_boundary

_HOST = "bocasocios-gw.bocajuniors.com.ar"
_PATH = "/auth/login/baas"
_URL = f"https://{_HOST}{_PATH}"
_MAX_RESPONSE = 65_536
_MAX_COOKIES = 64
_MAX_COOKIE_HEADER = 16_384
_COOKIE_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}\Z")
_COOKIE_VALUE = re.compile(r"[\x21\x23-\x2b\x2d-\x3a\x3c-\x5b\x5d-\x7e]{0,8192}\Z")


class BocaLoginTransportUnavailable(RuntimeError):
    """Category-only transport failure, without controller/vault dependencies."""


@dataclass(frozen=True, slots=True, repr=False)
class BocaSessionCookie:
    """Private snapshot from the current session, never a fabricated cookie jar.

    A leading dot on domain is required for a parent-domain cookie; a bare
    domain denotes a host-only cookie, matching browser-context snapshots.
    expires_at=None denotes a session cookie. The session adapter must normalize
    browser-specific expiry sentinels and must not read another browser profile.
    """

    name: str
    value: str
    domain: str
    path: str
    secure: bool
    expires_at: float | None = None

    def __repr__(self) -> str:
        return "BocaSessionCookie(<private values omitted>)"


class BocaLoginSession(Protocol):
    """Read only current cookies from the single owner-started worker session.

    This operation must not navigate, validate Queue-it, create a session or
    refresh anything. Return current browser-cookie metadata for scope checks.
    Empty means no cookies observed; it is never proof of login readiness.
    """

    def cookies_for_url(self, url: str) -> tuple[BocaSessionCookie, ...]: ...


class _HttpResponse(Protocol):
    status: int

    def getheader(self, name: str) -> str | None: ...

    def read(self, length: int, /) -> bytes: ...


class _HttpConnection(Protocol):
    def request(self, method: str, url: str, body: bytes, headers: dict[str, str]) -> None: ...

    def getresponse(self) -> _HttpResponse: ...

    def close(self) -> None: ...


def _require_worker_boundary() -> None:
    # The installed controller has no browser executor profile. Host attestation
    # separately establishes the dedicated rootless bridge; these process checks
    # cannot establish Docker network ownership or a genuine browser session.
    if os.environ.get("BOCA_BROWSER_EXECUTOR") != "automatic-observation":
        raise BocaLoginTransportUnavailable("Boca worker unavailable")
    validate_worker_boundary()
    interfaces = socket.if_nameindex()
    if len(interfaces) != 2 or {name for index, name in interfaces if index > 0} != {
        "lo",
        "eth0",
    }:
        raise BocaLoginTransportUnavailable("Boca worker unavailable")


def _cookie_header(cookies: tuple[BocaSessionCookie, ...], *, now: float) -> str:
    if not isinstance(cookies, tuple) or len(cookies) > _MAX_COOKIES or not isfinite(now):
        raise ValueError("invalid session snapshot")
    values: list[str] = []
    seen: set[str] = set()
    for cookie in cookies:
        if (
            not isinstance(cookie, BocaSessionCookie)
            or not isinstance(cookie.name, str)
            or not isinstance(cookie.value, str)
            or _COOKIE_NAME.fullmatch(cookie.name) is None
            or _COOKIE_VALUE.fullmatch(cookie.value) is None
            or not isinstance(cookie.domain, str)
            or not isinstance(cookie.path, str)
            or not 0 < len(cookie.domain) <= 253
            or not 0 < len(cookie.path) <= 2048
            or not cookie.path.startswith("/")
            or any(ord(char) < 33 or ord(char) > 126 for char in cookie.domain + cookie.path)
            or type(cookie.secure) is not bool
        ):
            raise ValueError("invalid session cookie")
        expiry = cookie.expires_at
        if expiry is not None and (type(expiry) not in (int, float) or not isfinite(expiry)):
            raise ValueError("invalid session cookie")
        domain = cookie.domain.lower()
        domain_cookie = domain.startswith(".")
        if domain_cookie:
            domain = domain[1:]
        # Do not send another portal's or Queue-it's cookies, nor accept broad
        # public-suffix scopes. These are the only applicable provider domains.
        path_matches = _PATH == cookie.path or (
            _PATH.startswith(cookie.path)
            and (cookie.path.endswith("/") or _PATH[len(cookie.path) :].startswith("/"))
        )
        if (
            not (domain == _HOST or (domain_cookie and domain == "bocajuniors.com.ar"))
            or not path_matches
            or not cookie.secure
            or (expiry is not None and expiry <= now)
        ):
            continue
        # Duplicate names with different scopes are ambiguous for this fixed
        # login exchange. Refuse rather than choosing an authentication cookie.
        if cookie.name in seen:
            raise ValueError("ambiguous session cookie")
        seen.add(cookie.name)
        values.append(f"{cookie.name}={cookie.value}")
    header = "; ".join(values)
    if len(header) > _MAX_COOKIE_HEADER:
        raise ValueError("session cookies exceed limit")
    return header


class BocaHttpLoginTransport:
    """Fixed-host HTTPS transport; caller owns START/STOP and session custody.

    Construction is inert. Each login checks the worker boundary, takes a new
    cookie snapshot and makes one request. HTTPSConnection follows no redirect,
    reads no proxy environment and performs no application retry. Its finite
    timeout bounds socket operations; host lifecycle owns the process deadline.
    Provider JSON/token validation remains in BocaMemberAuthService's parser.
    """

    def __init__(
        self,
        *,
        session: BocaLoginSession,
        connection_factory: Callable[..., _HttpConnection] = http.client.HTTPSConnection,
        timeout_seconds: float = 5.0,
        boundary_check: Callable[[], None] = _require_worker_boundary,
        now: Callable[[], float] = time,
    ) -> None:
        if (
            type(timeout_seconds) not in (int, float)
            or not isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 15
        ):
            raise ValueError("Boca timeout must be finite and bounded")
        self._session = session
        self._connection_factory = connection_factory
        self._timeout = float(timeout_seconds)
        self._boundary_check = boundary_check
        self._now = now

    def __repr__(self) -> str:
        return "BocaHttpLoginTransport(<private session omitted>)"

    def login(self, *, email: str, password: str) -> bytes:
        connection: _HttpConnection | None = None
        try:
            self._boundary_check()
            if (
                not isinstance(email, str)
                or not 0 < len(email) <= 320
                or not isinstance(password, str)
                or not 0 < len(password) <= 4096
            ):
                raise ValueError("invalid login credential")
            cookies = _cookie_header(self._session.cookies_for_url(_URL), now=self._now())
            body = json.dumps(
                {"email": email, "password": password}, separators=(",", ":"), ensure_ascii=True
            ).encode("ascii")
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": "https://bocasocios.bocajuniors.com.ar",
                "Referer": "https://bocasocios.bocajuniors.com.ar/",
            }
            if cookies:
                headers["Cookie"] = cookies
            connection = self._connection_factory(
                host=_HOST, timeout=self._timeout, context=ssl.create_default_context()
            )
            connection.request("POST", _PATH, body, headers)
            response = connection.getresponse()
            content_type = response.getheader("Content-Type")
            if (
                type(response.status) is not int
                or response.status != 200
                or not isinstance(content_type, str)
                or content_type.split(";", 1)[0].strip().lower() != "application/json"
            ):
                raise ValueError("unconfirmed login response")
            raw = response.read(_MAX_RESPONSE + 1)
            if not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX_RESPONSE:
                raise ValueError("unconfirmed login response")
            return raw
        except Exception:
            raise BocaLoginTransportUnavailable(
                "Boca login exchange unavailable or unverified"
            ) from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    raise BocaLoginTransportUnavailable(
                        "Boca login connection cleanup unverified"
                    ) from None
