"""Offline observation of an opaque queue pass for a future private owner view.

No Queue-it adapter, admission check, token generator, browser or network I/O.
This module does not authenticate the owner: the invoking private controller
must first enforce its existing passkey/session and request-protection gates.
Never send private details to logs, GitHub Actions, Telegram or public APIs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observation times must be timezone-aware")


class QueuePassState(StrEnum):
    """Observation result only; none of these states proves valid admission."""

    NOT_OBSERVED = "not_observed"
    OBSERVED_UNVERIFIED = "observed_unverified"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class QueuePassSummary:
    """Safe metadata for telemetry, statuses and public tests (no secrets)."""

    member_id: str
    event_id: str
    session_id: str
    state: QueuePassState
    observed_at: datetime | None
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class OwnerQueuePassDetails:
    """Sensitive ephemeral response for the already-authenticated private UI.

    Avoid logging, generic serialization, HTML embedding or artifact capture.
    The future UI must make retrieval explicitly owner-initiated and no-store.
    """

    state: QueuePassState
    observed_at: datetime | None
    expires_at: datetime | None
    target_url: str | None = field(repr=False)
    _full_token: str | None = field(repr=False)

    def copy_full_token(self) -> str:
        """Return the exact originally observed token, including all whitespace.

        This does not validate it or prove it can be used for entry.
        """
        if self._full_token is None:
            raise ValueError("no observed token is available")
        return self._full_token

    def copy_full_target_url(self) -> str:
        """Return the unmodified observed destination; never navigate to it."""
        if self.target_url is None:
            raise ValueError("no observed destination is available")
        return self.target_url


class QueuePassObservation:
    """In-memory metadata indexed by an existing member/event/session identity.

    There is deliberately no ticket quantity, queue operation or persistence
    here. Multiple sessions may be observed, but must not create requests.
    """

    __slots__ = (
        "member_id",
        "event_id",
        "session_id",
        "observed_at",
        "expires_at",
        "_full_token",
        "_target_url",
        "_unknown",
    )

    def __init__(
        self,
        *,
        member_id: str,
        event_id: str,
        session_id: str,
        observed_at: datetime | None = None,
        expires_at: datetime | None = None,
        token: str | None = None,
        target_url: str | None = None,
        unknown: bool = False,
    ) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                member_id,
                event_id,
                session_id,
            )
        ):
            raise ValueError("member_id, event_id and session_id must be nonblank")
        if token is not None and (not isinstance(token, str) or not token.strip()):
            raise ValueError("a supplied observation requires a nonblank token")
        if token is None and (observed_at is not None or expires_at is not None):
            raise ValueError("timestamps require an observed token")
        if token is not None and observed_at is None:
            raise ValueError("an observed token requires its observation time")
        if token is None and target_url is not None:
            raise ValueError("a target URL requires an observed token")
        if unknown and token is not None:
            raise ValueError("unknown and observed token states are mutually exclusive")
        if observed_at is not None:
            _aware(observed_at)
        if expires_at is not None:
            _aware(expires_at)
            if observed_at is None or expires_at < observed_at:
                raise ValueError("expiry must be at or after the observation")

        self.member_id = member_id
        self.event_id = event_id
        self.session_id = session_id
        self.observed_at = observed_at
        self.expires_at = expires_at
        self._full_token = token
        self._target_url = target_url
        self._unknown = unknown

    @classmethod
    def observed(
        cls,
        *,
        member_id: str,
        event_id: str,
        session_id: str,
        token: str,
        target_url: str | None,
        observed_at: datetime,
        expires_at: datetime | None = None,
    ) -> QueuePassObservation:
        """Wrap observer-supplied data; do not infer validity or navigate."""
        return cls(
            member_id=member_id,
            event_id=event_id,
            session_id=session_id,
            token=token,
            target_url=target_url,
            observed_at=observed_at,
            expires_at=expires_at,
        )

    @classmethod
    def not_observed(
        cls, *, member_id: str, event_id: str, session_id: str
    ) -> QueuePassObservation:
        return cls(member_id=member_id, event_id=event_id, session_id=session_id)

    @classmethod
    def unknown(cls, *, member_id: str, event_id: str, session_id: str) -> QueuePassObservation:
        return cls(member_id=member_id, event_id=event_id, session_id=session_id, unknown=True)

    def _state(self, *, at: datetime) -> QueuePassState:
        _aware(at)
        if self._unknown:
            return QueuePassState.UNKNOWN
        if self._full_token is None:
            return QueuePassState.NOT_OBSERVED
        if self.expires_at is not None and at >= self.expires_at:
            return QueuePassState.EXPIRED
        return QueuePassState.OBSERVED_UNVERIFIED

    def summary(self, *, at: datetime) -> QueuePassSummary:
        """Safe status for ordinary dashboard lists and diagnostics."""
        return QueuePassSummary(
            member_id=self.member_id,
            event_id=self.event_id,
            session_id=self.session_id,
            state=self._state(at=at),
            observed_at=self.observed_at,
            expires_at=self.expires_at,
        )

    def private_owner_details(
        self, *, owner_authenticated: bool, at: datetime
    ) -> OwnerQueuePassDetails:
        """Provide sensitive details only after the host confirms owner auth.

        `owner_authenticated` is an explicit *integration precondition*, not a
        substitute for performing passkey/session authorization in the panel.
        """
        if owner_authenticated is not True:
            raise PermissionError("authenticated owner required for private queue pass")
        return OwnerQueuePassDetails(
            state=self._state(at=at),
            observed_at=self.observed_at,
            expires_at=self.expires_at,
            target_url=self._target_url,
            _full_token=self._full_token,
        )

    def __repr__(self) -> str:
        """Never interpolate observed token or destination into diagnostics."""
        return (
            "QueuePassObservation("
            f"member_id={self.member_id!r}, "
            f"event_id={self.event_id!r}, "
            f"session_id={self.session_id!r}, "
            "private_values=<redacted>)"
        )
