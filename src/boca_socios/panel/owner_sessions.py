"""Bounded process-local sessions; the real owner authenticator is not supplied."""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from threading import Lock
from time import monotonic
from uuid import uuid4

_COOKIE = re.compile(r"__Host-boca_session=([A-Za-z0-9_-]{43})")


@dataclass(frozen=True, slots=True, repr=False)
class OwnerIdentity:
    subject: str
    permissions: frozenset[str]


def _deny(proof: object) -> None:
    return None


@dataclass(slots=True, repr=False)
class EnrollmentOperation:
    fingerprint: bytes | None = None
    state: str = "new"
    status: int = 503
    member_id: str | None = None


@dataclass(slots=True, repr=False)
class OwnerSession:
    created: float
    touched: float
    permissions: frozenset[str] = frozenset()
    csrf: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    fingerprint_key: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    operations: dict[str, EnrollmentOperation] = field(default_factory=dict)
    next_write: float = 0


class OwnerSessions:
    """Only a trusted internal authenticator may mint sessions; no login route.

    A restart revokes every session. Do not share this store across processes or
    represent its operation cache as durable exactly-once enrollment.
    """

    def __init__(
        self,
        *,
        owner_subject: str,
        verify_owner: Callable[[object], OwnerIdentity | None] = _deny,
        idle_timeout: timedelta = timedelta(minutes=15),
        absolute_timeout: timedelta = timedelta(hours=8),
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not owner_subject or len(owner_subject) > 128:
            raise ValueError("owner must be configured")
        self._idle = idle_timeout.total_seconds()
        self._absolute = absolute_timeout.total_seconds()
        if not 0 < self._idle <= self._absolute or not math.isfinite(self._absolute):
            raise ValueError("session lifetimes must be positive and bounded")
        self._owner = owner_subject
        self._verify = verify_owner
        self._clock = clock or monotonic
        self._sessions: dict[bytes, OwnerSession] = {}
        self._lock = Lock()

    def _live(self, session: OwnerSession, now: float) -> bool:
        return (
            math.isfinite(now)
            and session.touched <= now
            and now - session.touched < self._idle
            and now - session.created < self._absolute
        )

    @staticmethod
    def _key(cookie: object) -> bytes | None:
        if not isinstance(cookie, str) or len(cookie) > 100:
            return None
        match = _COOKIE.fullmatch(cookie)
        return hashlib.sha256(match.group(1).encode("ascii")).digest() if match else None

    def authenticate(self, proof: object) -> str | None:
        """Called only after the hosting authenticator verifies its proof.

        The verifier must validate freshness, origin and owner authentication;
        this method never treats a client identity header as proof.
        """
        try:
            identity = self._verify(proof)
            valid = (
                isinstance(identity, OwnerIdentity)
                and isinstance(identity.subject, str)
                and identity.subject == self._owner
                and isinstance(identity.permissions, frozenset)
                and "members:enroll" in identity.permissions
            )
            now = self._clock()
            if not valid or not math.isfinite(now):
                return None
        except Exception:
            return None
        assert isinstance(identity, OwnerIdentity)
        with self._lock:
            self._sessions = {
                key: value for key, value in self._sessions.items() if self._live(value, now)
            }
            if len(self._sessions) >= 32:
                return None
            token = secrets.token_urlsafe(32)
            self._sessions[hashlib.sha256(token.encode("ascii")).digest()] = OwnerSession(
                now, now, identity.permissions
            )
        return f"__Host-boca_session={token}; Path=/; Secure; HttpOnly; SameSite=Strict"

    def lookup(self, cookie: object) -> OwnerSession | None:
        key = self._key(cookie)
        if key is None:
            return None
        with self._lock:
            session = self._sessions.get(key)
            now = self._clock()
            if session is None:
                return None
            if not self._live(session, now):
                del self._sessions[key]
                return None
            session.touched = now
            return session

    def revoke(self, cookie: object) -> None:
        key = self._key(cookie)
        if key is not None:
            with self._lock:
                self._sessions.pop(key, None)

    def new_operation(self, session: OwnerSession) -> str | None:
        with self._lock:
            if (
                not any(value is session for value in self._sessions.values())
                or not self._live(session, self._clock())
                or len(session.operations) >= 16
            ):
                return None
            identifier = str(uuid4())
            session.operations[identifier] = EnrollmentOperation()
            return identifier

    def reserve(
        self, session: OwnerSession, operation_id: str, csrf: str, body: bytes
    ) -> tuple[int, EnrollmentOperation | None]:
        """0 means newly reserved; a recorded status is an immutable replay."""
        if not hmac.compare_digest(session.csrf.encode("ascii"), csrf.encode("utf-8")):
            return 403, None
        fingerprint = hmac.digest(session.fingerprint_key, body, "sha256")
        with self._lock:
            now = self._clock()
            if not any(value is session for value in self._sessions.values()) or not self._live(
                session, now
            ):
                return 401, None
            operation = session.operations.get(operation_id)
            if operation is None:
                return 409, None
            if operation.fingerprint is not None:
                if not hmac.compare_digest(operation.fingerprint, fingerprint):
                    return 409, None
                if operation.state == "pending":
                    return 409, None
                return operation.status, operation
            if now < session.next_write:
                return 429, None
            session.next_write = now + 1
            operation.fingerprint = fingerprint
            operation.state = "pending"
            return 0, operation

    def finish(
        self, operation: EnrollmentOperation, status: int, member_id: str | None = None
    ) -> None:
        with self._lock:
            operation.status = status
            operation.member_id = member_id
            operation.state = "finished"
