"""Bounded private projections of received member and global owner observations.

No listener, persistent bearer storage, token generation or site navigation.
The owner-passkey WSGI adapter is responsible for the real access check.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Literal

from boca_socios.browser.queue_page_observation import QueuePageObservation
from boca_socios.queue.pass_observation import (
    OwnerQueuePassDetails,
    QueuePassObservation,
    QueuePassSummary,
)


class PrivateQueuePassMonitor:
    def __init__(self, *, max_observations: int = 16) -> None:
        if not 1 <= max_observations <= 64:
            raise ValueError("private queue observation limit must be bounded")
        self._limit = max_observations
        self._lock = Lock()
        self._records: dict[tuple[str, str, str], QueuePassObservation] = {}

    def observe(self, observation: QueuePassObservation) -> None:
        if not isinstance(observation, QueuePassObservation):
            raise TypeError("only an existing queue observation can be recorded")
        key = (observation.member_id, observation.event_id, observation.session_id)
        with self._lock:
            if key not in self._records and len(self._records) >= self._limit:
                raise ValueError("private queue observation limit reached")
            self._records[key] = observation

    def list_summaries(self, *, at: datetime) -> tuple[QueuePassSummary, ...]:
        with self._lock:
            records = tuple(self._records[key] for key in sorted(self._records))
        return tuple(record.summary(at=at) for record in records)

    def owner_details(
        self,
        member_id: str,
        event_id: str,
        session_id: str,
        *,
        at: datetime,
        owner_authenticated: bool,
    ) -> OwnerQueuePassDetails | None:
        if owner_authenticated is not True:
            raise PermissionError("authenticated owner required for private queue pass")
        with self._lock:
            observation = self._records.get((member_id, event_id, session_id))
        return (
            observation.private_owner_details(at=at, owner_authenticated=True)
            if observation is not None
            else None
        )


ObservationCode = Literal[
    "automatic_checking",
    "automatic_observed",
    "automatic_no_event",
    "automatic_no_queue",
    "automatic_failed",
]


@dataclass(frozen=True, slots=True)
class TokenObservationActivity:
    """Fixed automatic source category, with no identity, URL or bearer value."""

    at: datetime
    code: ObservationCode


class PrivateAutomaticObservationMonitor:
    """Keep the latest real worker observation in the owner's global scope.

    An enabled source has no observation until the authenticated IPC producer
    returns one. No synthetic member, event or session is attached to a real
    token. This process-local projection is not a Boca login transport or an
    assertion that the provider has accepted the observed URL.
    """

    def __init__(
        self,
        *,
        configured: bool = False,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if type(configured) is not bool:
            raise ValueError("automatic source configuration unavailable")
        self._configured = configured
        self._now = now
        self._lock = Lock()
        self._latest: QueuePageObservation | None = None
        self._last_observed_at: datetime | None = None
        self._status = "AUTOMATIC_CONFIGURED" if configured else "NOT_CONFIGURED"
        self._activity: deque[TokenObservationActivity] = deque(maxlen=32)

    def _instant(self) -> datetime:
        now = self._now()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("observation clock unavailable")
        return now.astimezone(UTC)

    def mark_checking(self) -> None:
        if not self._configured:
            raise RuntimeError("automatic source is not configured")
        now = self._instant()
        with self._lock:
            # A new check never displays a prior activation's bearer as current.
            self._latest = None
            self._status = "AUTOMATIC_CHECKING"
            self._activity.append(TokenObservationActivity(now, "automatic_checking"))

    def observe_global(self, observation: QueuePageObservation) -> None:
        if not self._configured:
            raise RuntimeError("automatic source is not configured")
        if not isinstance(observation, QueuePageObservation):
            raise TypeError("only a received queue page observation can be recorded")
        now = self._instant()
        with self._lock:
            if observation.observed_at > now or (
                self._last_observed_at is not None
                and observation.observed_at < self._last_observed_at
            ):
                raise ValueError("observation time unavailable")
            code: ObservationCode
            if observation.outcome == "NO_EVENT_OBSERVED":
                self._status, code = "AUTOMATIC_NO_EVENT", "automatic_no_event"
            elif observation.outcome == "QUEUE_INACTIVE":
                self._status, code = "AUTOMATIC_NO_QUEUE", "automatic_no_queue"
            elif observation.outcome in {"CHECK_FAILED", "CHALLENGE", "UNKNOWN"}:
                self._status, code = "AUTOMATIC_FAILED", "automatic_failed"
            else:
                self._status, code = "AUTOMATIC_OBSERVED", "automatic_observed"
            self._latest = observation
            self._last_observed_at = observation.observed_at
            self._activity.append(TokenObservationActivity(observation.observed_at, code))

    def activity_events(self) -> tuple[TokenObservationActivity, ...]:
        with self._lock:
            return tuple(self._activity)

    def snapshot(self) -> dict[str, object]:
        """Only automatic source state and redacted evidence, never the URL."""
        now = self._instant()
        with self._lock:
            return {
                "version": 1,
                "scope": "OWNER_GLOBAL",
                "source": "AUTOMATIC_QUEUE",
                "status": self._status,
                "configured": self._configured,
                "latest": self._latest.metadata() if self._latest is not None else None,
                "has_target_url": self._latest is not None and self._latest.target_url is not None,
                "observed_at": now.isoformat(),
            }

    def owner_global_details(self, *, owner_authenticated: bool) -> QueuePageObservation | None:
        if owner_authenticated is not True:
            raise PermissionError("authenticated owner required for private queue observation")
        with self._lock:
            return self._latest
