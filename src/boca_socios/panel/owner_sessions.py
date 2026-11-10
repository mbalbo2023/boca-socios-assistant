"""Owner sessions: process-local CSRF/operations and opt-in durable authorization."""

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

from boca_socios.panel.owner_session_store import OwnerBrowserSessionStore

_COOKIE = re.compile(r"__Host-boca_session=([A-Za-z0-9_-]{43})")
_MAX_COOKIE_HEADER = 4096
_MAX_COOKIES = 32
_CHROME_MAX_AGE_SECONDS = 34_560_000  # 400 days; rolling on authenticated HTTP requests


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
    form_scope: bytes | None = None
    lifecycle_id: str | None = None


@dataclass(slots=True, repr=False)
class OwnerSession:
    created: float
    touched: float
    permissions: frozenset[str] = frozenset()
    csrf: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    fingerprint_key: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    operations: dict[str, EnrollmentOperation] = field(default_factory=dict)
    next_write: float = 0
    next_priority_stop: float = 0


class OwnerSessions:
    """Only a trusted internal authenticator may mint sessions.

    The durable mode persists ONLY a hash of the authorized bearer token and a
    binding to the configured owner verifier, never CSRF/operation data. There
    is exactly one global owner session; a new passkey login replaces the old.
    Ephemeral mode remains available for legacy isolated unit tests.
    """

    def __init__(
        self,
        *,
        owner_subject: str,
        verify_owner: Callable[[object], OwnerIdentity | None] = _deny,
        idle_timeout: timedelta = timedelta(minutes=15),
        absolute_timeout: timedelta = timedelta(hours=8),
        clock: Callable[[], float] | None = None,
        persistent_store: OwnerBrowserSessionStore | None = None,
        authorization_binding: bytes | None = None,
        restore_permissions: frozenset[str] | None = None,
    ) -> None:
        if not owner_subject or len(owner_subject) > 128:
            raise ValueError("owner must be configured")
        self._idle = idle_timeout.total_seconds()
        self._absolute = absolute_timeout.total_seconds()
        if not 0 < self._idle <= self._absolute or not math.isfinite(self._absolute):
            raise ValueError("session lifetimes must be positive and bounded")
        if persistent_store is not None and (
            not isinstance(persistent_store, OwnerBrowserSessionStore)
            or not isinstance(authorization_binding, bytes)
            or len(authorization_binding) != 32
            or not isinstance(restore_permissions, frozenset)
            or "members:enroll" not in restore_permissions
        ):
            raise ValueError("durable sessions require an exact trusted owner verifier binding")
        if persistent_store is None and (
            authorization_binding is not None or restore_permissions is not None
        ):
            raise ValueError("unexpected verifier for process-local sessions")
        self._owner = owner_subject
        self._verify = verify_owner
        self._clock = clock or monotonic
        self._sessions: dict[bytes, OwnerSession] = {}
        self._lock = Lock()
        self._persistent = persistent_store
        self._binding = authorization_binding
        self._restore_permissions = restore_permissions

    def _live(self, session: OwnerSession, now: float) -> bool:
        if self._persistent is not None:
            # The browser, logout, replacement or verifier rotation governs
            # lifetime; not the old 15-minute idle / 8-hour absolute windows.
            return math.isfinite(now)
        return (
            math.isfinite(now)
            and session.touched <= now
            and now - session.touched < self._idle
            and now - session.created < self._absolute
        )

    @staticmethod
    def _token(cookie: object) -> str | None:
        if not isinstance(cookie, str) or len(cookie) > _MAX_COOKIE_HEADER:
            return None
        parts = cookie.split(";")
        if len(parts) > _MAX_COOKIES:
            return None
        token: str | None = None
        for part in parts:
            pair = part.strip()
            name, separator, _ = pair.partition("=")
            if not separator or not name:
                return None
            if name == "__Host-boca_session":
                match = _COOKIE.fullmatch(pair)
                if token is not None or match is None:
                    return None
                token = match.group(1)
        return token

    @classmethod
    def _key(cls, cookie: object) -> bytes | None:
        token = cls._token(cookie)
        return hashlib.sha256(token.encode("ascii")).digest() if token is not None else None

    @staticmethod
    def _cookie(token: str, *, persistent: bool) -> str:
        value = f"__Host-boca_session={token}; Path=/; Secure; HttpOnly; SameSite=Strict"
        if persistent:
            value += f"; Max-Age={_CHROME_MAX_AGE_SECONDS}"
        return value

    def _member_key(self, session: OwnerSession, now: float) -> bytes | None:
        """Called under self._lock, including a durable revocation check."""
        for key, value in self._sessions.items():
            if value is session and self._live(session, now):
                if self._persistent is not None:
                    assert self._binding is not None
                    if not self._persistent.matches(key, self._binding):
                        return None
                return key
        return None

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
                and (self._persistent is None or identity.permissions == self._restore_permissions)
            )
            now = self._clock()
            if not valid or not math.isfinite(now):
                return None
        except Exception:
            return None
        assert isinstance(identity, OwnerIdentity)
        with self._lock:
            token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode("ascii")).digest()
            if self._persistent is not None:
                assert self._binding is not None
                self._persistent.replace(digest, self._binding)
                self._sessions.clear()
            else:
                self._sessions = {
                    key: value for key, value in self._sessions.items() if self._live(value, now)
                }
                if len(self._sessions) >= 32:
                    return None
            self._sessions[digest] = OwnerSession(now, now, identity.permissions)
        return self._cookie(token, persistent=self._persistent is not None)

    def lookup(self, cookie: object) -> OwnerSession | None:
        key = self._key(cookie)
        if key is None:
            return None
        with self._lock:
            now = self._clock()
            if self._persistent is not None:
                assert self._binding is not None
                if not self._persistent.matches(key, self._binding):
                    self._sessions.pop(key, None)
                    return None
                session = self._sessions.get(key)
                if session is None:
                    # Different controller lifetime: preserve authorization,
                    # rotate process-local CSRF/fingerprint/operation namespace.
                    assert self._restore_permissions is not None
                    session = OwnerSession(now, now, self._restore_permissions)
                    self._sessions = {key: session}
            else:
                session = self._sessions.get(key)
            if session is None:
                return None
            if not self._live(session, now):
                del self._sessions[key]
                return None
            session.touched = now
            return session

    def renew_cookie(self, cookie: object, session: OwnerSession) -> str | None:
        """Issue a new 400-day browser window without minting a new bearer."""
        if self._persistent is None:
            return None
        token = self._token(cookie)
        if token is None:
            return None
        key = hashlib.sha256(token.encode("ascii")).digest()
        with self._lock:
            if self._sessions.get(key) is not session:
                return None
            assert self._binding is not None
            if not self._persistent.matches(key, self._binding):
                return None
            return self._cookie(token, persistent=True)

    def revoke(self, cookie: object) -> None:
        key = self._key(cookie)
        if key is not None:
            with self._lock:
                if self._persistent is not None:
                    assert self._binding is not None
                    self._persistent.revoke_matching(key, self._binding)
                self._sessions.pop(key, None)

    def new_operation(
        self, session: OwnerSession, *, form_scope: bytes | None = None
    ) -> str | None:
        with self._lock:
            if self._member_key(session, self._clock()) is None:
                return None
            if form_scope is not None:
                # Reading the same status page must not consume another form
                # nonce. Retain old completed receipts within the session cap.
                for identifier, prior in session.operations.items():
                    if prior.form_scope == form_scope and prior.state == "new":
                        return identifier
                if len(session.operations) >= 16:
                    spent = next(
                        (
                            key
                            for key, prior in session.operations.items()
                            if prior.form_scope is not None and prior.state == "finished"
                        ),
                        None,
                    )
                    if spent is not None:
                        del session.operations[spent]
            if len(session.operations) >= 16:
                return None
            identifier = str(uuid4())
            session.operations[identifier] = EnrollmentOperation(form_scope=form_scope)
            return identifier

    def reserve(
        self,
        session: OwnerSession,
        operation_id: str,
        csrf: str,
        body: bytes,
        *,
        pending_start: Callable[[], bool] | None = None,
    ) -> tuple[int, EnrollmentOperation | None]:
        """0 means newly reserved; a recorded status is an immutable replay."""
        if not hmac.compare_digest(session.csrf.encode("ascii"), csrf.encode("utf-8")):
            return 403, None
        fingerprint = hmac.digest(session.fingerprint_key, body, "sha256")
        with self._lock:
            now = self._clock()
            if self._member_key(session, now) is None:
                return 401, None
            operation = session.operations.get(operation_id)
            if operation is None:
                return 409, None
            if operation.form_scope is not None and operation.form_scope != body:
                return 409, None
            if operation.fingerprint is not None:
                if not hmac.compare_digest(operation.fingerprint, fingerprint):
                    return 409, None
                if operation.state == "pending":
                    return 409, None
                return operation.status, operation
            if now < session.next_write:
                # A second, independently bounded write lets the owner cancel
                # a START immediately, including before its first host claim.
                if pending_start is None or now < session.next_priority_stop or not pending_start():
                    return 429, None
                session.next_priority_stop = now + 1
            session.next_write = now + 1
            operation.fingerprint = fingerprint
            operation.state = "pending"
            return 0, operation

    def finish(
        self,
        operation: EnrollmentOperation,
        status: int,
        member_id: str | None = None,
        *,
        lifecycle_id: str | None = None,
    ) -> None:
        with self._lock:
            operation.status = status
            operation.member_id = member_id
            operation.lifecycle_id = lifecycle_id
            operation.state = "finished"
