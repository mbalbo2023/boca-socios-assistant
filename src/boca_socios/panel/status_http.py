"""Dormant WSGI adapter for a fixed, owner-only local status projection.

No listener, identity provider, TLS terminator or runtime wiring is installed
here. The hosting boundary must supply authenticated identity verification.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from threading import Lock
from time import monotonic

from boca_socios.panel.local_status import read_local_status


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    subject: str
    permissions: frozenset[str]
    expires_at: datetime


IdentityVerifier = Callable[[str, datetime], VerifiedIdentity | None]
StartResponse = Callable[[str, list[tuple[str, str]]], object]
_TOKEN = re.compile(r"Bearer ([A-Za-z0-9._~-]{1,1024})")
_PATH = "/api/v1/local-status"


def _deny_identity(token: str, now: datetime) -> None:
    return None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _response(
    start_response: StartResponse, status: int, payload: bytes, *, retry: bool = False
) -> list[bytes]:
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(payload))),
        ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"),
        ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
    ]
    if status == 405:
        headers.append(("Allow", "GET"))
    if status == 401:
        headers.append(("WWW-Authenticate", 'Bearer realm="boca-local-status"'))
    if retry:
        headers.append(("Retry-After", "1"))
    start_response(f"{status} {HTTPStatus(status).phrase}", headers)
    return [payload]


def _error(start_response: StartResponse, status: int, code: str) -> list[bytes]:
    payload = json.dumps({"error": code}, separators=(",", ":")).encode("ascii")
    return _response(start_response, status, payload, retry=status == 429)


class StatusApplication:
    """A non-serving request boundary; verification defaults to rejecting all.

    The configured database path and owner are server configuration, never
    request inputs. This first adapter rejects cookie and cross-origin access.
    A future Site integration needs a reviewed identity and gateway contract.
    """

    def __init__(
        self,
        database_path: Path,
        *,
        owner_subject: str,
        verify_identity: IdentityVerifier = _deny_identity,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not database_path.is_absolute():
            raise ValueError("database path must be absolute")
        if not owner_subject or len(owner_subject) > 128:
            raise ValueError("owner subject must be configured")
        self._database_path = database_path
        self._owner = owner_subject
        self._verify = verify_identity
        self._now = now
        self._read_lock = Lock()
        self._next_read = 0.0

    def __call__(self, environ: Mapping[str, object], start_response: StartResponse) -> list[bytes]:
        # Never trust an incoming forwarded-proto header as proof of TLS.
        if environ.get("wsgi.url_scheme") != "https":
            return _error(start_response, 400, "secure_transport_required")
        if environ.get("PATH_INFO") != _PATH:
            return _error(start_response, 404, "not_found")
        if environ.get("REQUEST_METHOD") != "GET":
            return _error(start_response, 405, "method_not_allowed")
        if (
            environ.get("QUERY_STRING", "") != ""
            or environ.get("CONTENT_LENGTH", "") not in ("", "0")
            or environ.get("HTTP_TRANSFER_ENCODING", "") != ""
            or environ.get("HTTP_COOKIE", "") != ""
        ):
            return _error(start_response, 400, "invalid_request")
        if environ.get("HTTP_ORIGIN", "") != "":
            return _error(start_response, 403, "origin_not_enabled")
        authorization = environ.get("HTTP_AUTHORIZATION")
        if not isinstance(authorization, str) or len(authorization) > 1031:
            return _error(start_response, 401, "authentication_required")
        match = _TOKEN.fullmatch(authorization)
        if match is None:
            return _error(start_response, 401, "authentication_required")
        try:
            now = self._now()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("invalid clock")
            identity = self._verify(match.group(1), now)
        except Exception:
            return _error(start_response, 503, "identity_unavailable")
        if identity is None:
            return _error(start_response, 401, "authentication_required")
        try:
            permitted = (
                isinstance(identity, VerifiedIdentity)
                and isinstance(identity.subject, str)
                and identity.subject == self._owner
                and isinstance(identity.permissions, frozenset)
                and "local-status:read" in identity.permissions
                and isinstance(identity.expires_at, datetime)
                and identity.expires_at.tzinfo is not None
                and identity.expires_at.utcoffset() is not None
                and identity.expires_at > now
            )
        except Exception:
            return _error(start_response, 503, "identity_unavailable")
        if not permitted:
            return _error(start_response, 403, "read_not_permitted")
        # One read at a time and at most one per second per app instance.
        # Hosting still needs a global request budget across workers.
        if not self._read_lock.acquire(blocking=False):
            return _error(start_response, 429, "read_rate_limited")
        try:
            current = monotonic()
            if current < self._next_read:
                return _error(start_response, 429, "read_rate_limited")
            self._next_read = current + 1.0
            try:
                snapshot = read_local_status(self._database_path, observed_at=now)
                data = asdict(snapshot)
                data["observed_at"] = snapshot.observed_at.isoformat()
                data["last_local_update_at"] = (
                    snapshot.last_local_update_at.isoformat()
                    if snapshot.last_local_update_at is not None
                    else None
                )
                payload = json.dumps(data, separators=(",", ":")).encode("utf-8")
                if len(payload) > 2048:
                    raise ValueError("response exceeds budget")
            except Exception:
                return _error(start_response, 503, "local_status_unavailable")
            return _response(start_response, 200, payload)
        finally:
            self._read_lock.release()
