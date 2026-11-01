"""Opt-in durable coordinator for local synthetic work only."""

from __future__ import annotations

from collections.abc import Callable
from math import isfinite
from time import time

from boca_socios.browser.contracts import (
    SimulationNotice,
    SimulationOutcome,
    SimulationReceipt,
    SyntheticBrowserPort,
)
from boca_socios.domain.policy import TicketIntent
from boca_socios.integration.offline import LocalNoticeStore, OfflineSimulation, StaticOutboxAdapter
from boca_socios.queue import InvalidStateTransition, OfflineQueueSimulator
from boca_socios.reservation_guard import (
    ReservationAttemptGuard,
    ReservationResolution,
    ReservationState,
)
from boca_socios.storage.database import Database


class DurableOfflineSimulation(OfflineSimulation):
    """One durable browser claim; completed local results may replay notices.

    Call prepare_storage explicitly before use. No default runtime imports or
    migration changes are introduced. Failed or interrupted work is never retried.
    """

    def __init__(
        self,
        *,
        database: Database,
        queue: OfflineQueueSimulator,
        outbox: LocalNoticeStore,
        browser: SyntheticBrowserPort,
        clock: Callable[[], float] = time,
    ) -> None:
        super().__init__(database=database, queue=queue, outbox=outbox, browser=browser)
        self._guard = ReservationAttemptGuard(database)
        self._clock = clock

    def prepare_storage(self) -> None:
        self._guard.migrate_simulation()

    def _clock_now(self) -> float:
        value = self._clock()
        if type(value) not in (int, float) or not isfinite(value) or value < 0:
            raise ValueError("clock must return finite nonnegative Unix seconds")
        return float(value)

    async def _run_workflow(
        self, intent: TicketIntent, notification_at_seconds: float
    ) -> SimulationReceipt:
        started = self._clock_now()
        request_id = self._database.request_ticket(intent)
        claim = self._guard.claim_simulation(request_id, now=started)
        if claim is None:
            snapshot = self._guard.get(request_id)
            if snapshot is None or snapshot.state is not ReservationState.SIMULATION_COMPLETED:
                raise InvalidStateTransition("durable synthetic attempt is consumed or unresolved")
        else:
            try:
                outcome = await self._browser.simulate_general_reservation()
                if outcome is not SimulationOutcome.RESERVED_IN_SIMULATOR:
                    raise ValueError("unexpected synthetic browser outcome")
            except BaseException:
                self._guard.resolve(
                    claim, ReservationResolution.SIMULATION_FAILED, now=self._clock_now()
                )
                raise
            self._guard.resolve(
                claim, ReservationResolution.SIMULATION_COMPLETED, now=self._clock_now()
            )
        # Completion is durable before notification. A later replay can recover
        # a missing notice without executing the browser a second time.
        outcome = SimulationOutcome.RESERVED_IN_SIMULATOR
        StaticOutboxAdapter(self._outbox, notification_at_seconds).publish_simulation_notice(
            SimulationNotice(request_id=request_id, outcome=outcome)
        )
        return SimulationReceipt(request_id=request_id, outcome=outcome)
