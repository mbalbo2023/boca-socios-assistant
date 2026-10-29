"""One admitted synthetic queue entry through a fake browser and local notice.

This opt-in coordinator has no credentials, HTTP client, real reservation state,
or live runtime wiring. A local intent is not an external purchase guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import NAMESPACE_OID, UUID, uuid5

from boca_socios.browser.contracts import (
    SimulationNotice,
    SimulationReceipt,
    SyntheticBrowserPort,
    SyntheticBrowserWorkflow,
)
from boca_socios.domain.policy import TicketIntent
from boca_socios.notify import NoticeKind, NotificationRecord, NotificationRequest
from boca_socios.queue import InvalidStateTransition, OfflineQueueSimulator, QueueState
from boca_socios.storage.database import Database


@dataclass(frozen=True, slots=True)
class SqliteIntentAdapter:
    database: Database

    def ensure_ticket_intent(self, intent: TicketIntent) -> str:
        return self.database.request_ticket(intent)


class LocalNoticeStore(Protocol):
    """Shared safe enqueue contract for memory and SQLite implementations."""

    def enqueue(self, request: NotificationRequest, *, now: float) -> NotificationRecord: ...


@dataclass(frozen=True, slots=True)
class StaticOutboxAdapter:
    """A stable, safe local notice key; no member details enter the outbox."""

    outbox: LocalNoticeStore
    now: float

    def publish_simulation_notice(self, notice: SimulationNotice) -> None:
        # The DB request ID is an opaque UUID. The namespace distinguishes this
        # notification from any future, separately reviewed notice kind.
        request_id = UUID(notice.request_id)
        key = uuid5(NAMESPACE_OID, f"boca-socios:synthetic-result:{request_id}")
        self.outbox.enqueue(
            NotificationRequest(idempotency_key=key, kind=NoticeKind.STATE_CHANGED),
            now=self.now,
        )


class OfflineSimulation:
    """Run an already-admitted fake queue entry once in this process.

    The queue is process-local. Another worker, restart, or ambiguous external
    result would require a durable claim and reconciliation before live use.
    """

    def __init__(
        self,
        *,
        database: Database,
        queue: OfflineQueueSimulator,
        outbox: LocalNoticeStore,
        browser: SyntheticBrowserPort,
    ) -> None:
        self._database = database
        self._queue = queue
        self._outbox = outbox
        self._browser = browser

    async def run_admitted(
        self,
        intent: TicketIntent,
        *,
        session_id: str,
        at: datetime,
        notification_at_seconds: float,
    ) -> SimulationReceipt:
        intent.validate()
        if intent.event_id != self._queue.config.event_id:
            raise ValueError("intent belongs to a different simulated event")
        self._queue.advance(at)
        snapshot = self._queue.snapshot(session_id)
        if snapshot.member_id != intent.member_id or snapshot.state is not QueueState.ADMITTED:
            raise InvalidStateTransition("synthetic admission is required for this member")
        workflow = SyntheticBrowserWorkflow(
            intents=SqliteIntentAdapter(self._database),
            browser=self._browser,
            notifications=StaticOutboxAdapter(self._outbox, notification_at_seconds),
        )
        receipt = await workflow.run(intent)
        self._queue.finish(session_id, at)
        return receipt
