"""Bounded process-local projection of externally supplied Queue-it observations.

No listener, storage, token generator, URL validation or site navigation.
The owner-passkey WSGI adapter is responsible for the real access check.
"""

from __future__ import annotations

from datetime import datetime
from threading import Lock

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
