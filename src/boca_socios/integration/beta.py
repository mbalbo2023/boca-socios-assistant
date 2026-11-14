"""Callable, on-demand BETA commands with durable local-only outcomes."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from time import time
from typing import Literal
from uuid import uuid4

from boca_socios.browser.contracts import SimulationNotice, SimulationOutcome, SyntheticBrowserPort
from boca_socios.domain.policy import TicketIntent
from boca_socios.domain.sector_preferences import SectorEvaluation
from boca_socios.integration.command_store import (
    CommandCapacityError,
    CommandConflict,
    CommandSnapshot,
    CommandState,
    CommandStore,
)
from boca_socios.integration.durable import DurableOfflineSimulation
from boca_socios.integration.offline import StaticOutboxAdapter
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.panel.lifecycle_intents import LifecycleIntentStore
from boca_socios.panel.worker_activity import record_simulation_queue_stage
from boca_socios.queue import OfflineQueueSimulator, SimulatorConfig
from boca_socios.reservation_guard import ReservationAttemptGuard, ReservationState
from boca_socios.storage.database import Database

__all__ = [
    "BetaCoordinator",
    "CommandCapacityError",
    "CommandConflict",
    "CommandSnapshot",
    "CommandState",
    "OnDemandBotSession",
]


@dataclass(frozen=True, slots=True)
class OnDemandBotSession:
    ledger: LifecycleIntentStore
    check_worker: Callable[[], None]
    wake: Callable[[str], None]
    on_start: Callable[[str], None] | None = None

    def require_start(self, status: Literal["CLAIMED", "APPLIED"]) -> str:
        state = self.ledger.current()
        if (
            state is None
            or not state.on_demand
            or state.component != "bot"
            or state.target != "start"
            or state.status != status
        ):
            raise RuntimeError("on-demand bot START unavailable")
        self.check_worker()
        return state.operation_id

    def before_engine_start(self) -> None:
        # Only the host's live claim can start this engine. An old APPLIED
        # START on disk can never reopen it after a controller restart.
        start_id = self.require_start("CLAIMED")
        if self.on_start is not None:
            self.on_start(start_id)

    def finish(self, start_operation_id: str) -> bool:
        stop = self.ledger.request_work_stop(start_operation_id)
        if stop is not None and stop.status == "REQUESTED":
            try:
                self.wake(stop.operation_id)
            except OSError:
                # The correlated STOP is durable. Its same UUID can be
                # delivered again; no new work may enter this engine.
                pass
        return stop is not None


class BetaCoordinator:
    """One bounded worker starts only when commands arrive or startup recovers.

    Hosting owns authentication and a single service lifecycle. No listeners,
    real browser/site access or provider notification transport are implemented.
    """

    def __init__(
        self,
        *,
        database: Database,
        outbox: SqliteNotificationOutbox,
        browser: SyntheticBrowserPort,
        clock: Callable[[], float] = time,
        max_pending: int = 16,
        timeout_seconds: float = 5,
        bot_session: OnDemandBotSession | None = None,
        sector_policy: Callable[[TicketIntent], SectorEvaluation] | None = None,
    ) -> None:
        if outbox.database is not database:
            raise ValueError("coordinator and outbox must share the same Database instance")
        if type(max_pending) is not int or not 1 <= max_pending <= 100:
            raise ValueError("pending capacity must be an integer between 1 and 100")
        if (
            type(timeout_seconds) not in (int, float)
            or not isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 30
        ):
            raise ValueError("synthetic timeout must be finite and in (0,30]")
        self._db = database
        self._outbox = outbox
        self._browser = browser
        self._clock = clock
        self._max_pending = max_pending
        self._timeout = timeout_seconds
        self._bot_session = bot_session
        self._sector_policy = sector_policy
        self._work_start_id: str | None = None
        self._store = CommandStore(database)
        self._guard = ReservationAttemptGuard(database)
        self._worker: asyncio.Task[None] | None = None
        self._active: asyncio.Task[None] | None = None
        self._active_key: str | None = None
        self._active_member: str | None = None
        self._failed = False
        self._closed = False

    @property
    def failed(self) -> bool:
        return self._failed

    def prepare_storage(self) -> None:
        """Explicit opt-in; never called by construction, begin, or recovery."""
        self._outbox.migrate()
        self._guard.migrate_simulation()
        self._store.migrate()

    def _now(self) -> float:
        now = self._clock()
        if type(now) not in (int, float) or not isfinite(now) or now < 0:
            raise ValueError("clock must return finite nonnegative Unix seconds")
        return float(now)

    async def begin(self, command_id: str, intent: TicketIntent) -> CommandSnapshot:
        if self._closed or self._failed:
            raise RuntimeError("local command service is unavailable")
        start_id = None
        bind_work = None
        if self._bot_session is not None:
            start_id = self._bot_session.require_start("APPLIED")
            if self._work_start_id is not None and self._work_start_id != start_id:
                raise RuntimeError("on-demand bot session has changed")
            ledger = self._bot_session.ledger
            confirmed_start = start_id

            def bind_work(connection: sqlite3.Connection, key: str) -> None:
                ledger.bind_work(connection, confirmed_start, key)

        snapshot = self._store.enqueue(
            command_id,
            intent,
            now=self._now(),
            max_pending=self._max_pending,
            bind_work=bind_work,
            sector_policy=self._sector_policy,
        )
        if snapshot.state is CommandState.ACCEPTED:
            self._work_start_id = start_id
        self._kick()
        return snapshot

    def status(self, command_id: str, *, member_id: str) -> CommandSnapshot | None:
        self._require_member(member_id)
        return self._store.get(command_id, member_id=member_id)

    async def stop(self, command_id: str, *, member_id: str) -> CommandSnapshot | None:
        self._require_member(member_id)
        result = self._store.stop(command_id, member_id=member_id, now=self._now())
        if (
            result is not None
            and result.state is CommandState.STOP_REQUESTED
            and result.command_id == self._active_key
        ):
            if self._active is not None:
                self._active.cancel()
        return result

    @staticmethod
    def _require_member(member_id: str) -> None:
        if not isinstance(member_id, str) or not member_id.strip():
            raise ValueError("member identity must be a nonblank string")

    def _kick(self) -> None:
        if not self._closed and not self._failed and (self._worker is None or self._worker.done()):
            self._worker = asyncio.create_task(self._drain())

    async def _simulate(self, intent: TicketIntent, *, command_id: str) -> None:
        # This is a local one-entry queue exercise, never a Queue-it admission.
        instant = datetime.fromtimestamp(self._now(), UTC)
        queue = OfflineQueueSimulator(
            SimulatorConfig(intent.event_id, instant, instant + timedelta(minutes=1))
        )
        session_id = str(uuid4())
        created = queue.create_session(intent.member_id, session_id, instant)
        record_simulation_queue_stage(self._db, command_id=command_id, snapshot=created, at=instant)
        waiting = queue.join(session_id, instant)
        record_simulation_queue_stage(self._db, command_id=command_id, snapshot=waiting, at=instant)
        admitted = queue.admit_next(instant)
        if admitted is None:
            raise RuntimeError("local queue admission unavailable")
        record_simulation_queue_stage(
            self._db, command_id=command_id, snapshot=admitted, at=instant
        )
        simulation = DurableOfflineSimulation(
            database=self._db,
            queue=queue,
            outbox=self._outbox,
            browser=self._browser,
            clock=self._clock,
        )
        try:
            await simulation.run_admitted(
                intent, session_id=session_id, at=instant, notification_at_seconds=self._now()
            )
        except asyncio.CancelledError:
            ended = queue.cancel(session_id, instant)
            record_simulation_queue_stage(
                self._db,
                command_id=command_id,
                snapshot=ended,
                at=datetime.fromtimestamp(self._now(), UTC),
            )
            raise
        except Exception:
            ended = queue.fail(session_id, instant)
            record_simulation_queue_stage(
                self._db,
                command_id=command_id,
                snapshot=ended,
                at=datetime.fromtimestamp(self._now(), UTC),
            )
            raise
        record_simulation_queue_stage(
            self._db,
            command_id=command_id,
            snapshot=queue.snapshot(session_id),
            at=datetime.fromtimestamp(self._now(), UTC),
        )

    def _reconcile(self, snapshot: CommandSnapshot) -> None:
        guard = self._guard.get(snapshot.request_id)
        if guard is not None and guard.state is ReservationState.SIMULATION_COMPLETED:
            self._store.settle(snapshot.command_id, CommandState.COMPLETED, now=self._now())
            # Stable notice ID recovers either side of the enqueue/ledger boundary.
            StaticOutboxAdapter(self._outbox, self._now()).publish_simulation_notice(
                SimulationNotice(snapshot.request_id, SimulationOutcome.RESERVED_IN_SIMULATOR)
            )
            self._store.mark_notice(snapshot.command_id, now=self._now())
        elif guard is not None and guard.state is ReservationState.SIMULATION_FAILED:
            state = (
                CommandState.STOPPED
                if snapshot.state is CommandState.STOP_REQUESTED
                else CommandState.FAILED
            )
            self._store.settle(snapshot.command_id, state, now=self._now())
        elif guard is None and snapshot.state is CommandState.STOP_REQUESTED:
            self._store.settle(snapshot.command_id, CommandState.STOPPED, now=self._now())
        else:
            self._store.settle(snapshot.command_id, CommandState.NEEDS_REVIEW, now=self._now())

    async def _drain(self) -> None:
        try:
            may_run = None
            if self._bot_session is not None:
                start_id = self._work_start_id
                if start_id is None:
                    return
                ledger = self._bot_session.ledger

                def may_run(connection: sqlite3.Connection, key: str) -> bool:
                    return ledger.may_run_work(connection, start_id, key)

            while not self._closed:
                claimed = self._store.claim_next(now=self._now(), may_run=may_run)
                if claimed is None:
                    if self._bot_session is not None and self._work_start_id is not None:
                        # An active automatic queue may outlive this local
                        # simulation. Admit later commands until the ledger
                        # actually derives STOP; admission also rechecks START
                        # inside its transaction to fence a concurrent stop.
                        self._closed = self._bot_session.finish(self._work_start_id)
                    break
                record, intent = claimed
                self._active_key, self._active_member = record.command_id, intent.member_id
                current = self._store.get(record.command_id)
                if current is None:
                    raise RuntimeError("claimed local command disappeared")
                if current.state is not CommandState.STOP_REQUESTED:
                    self._active = asyncio.create_task(
                        asyncio.wait_for(
                            self._simulate(intent, command_id=record.command_id), self._timeout
                        )
                    )
                    try:
                        await self._active
                    except (Exception, asyncio.CancelledError):  # noqa: S110
                        # Adapter errors may contain secrets; the durable guard records the outcome.
                        pass
                current = self._store.get(record.command_id)
                if current is None:
                    raise RuntimeError("claimed local command disappeared")
                self._reconcile(current)
                self._active = None
                self._active_key = self._active_member = None
        except Exception:
            self._failed = True
        finally:
            self._active = None
            self._active_key = self._active_member = None

    async def recover(self) -> None:
        """Startup-only, with exclusive lifecycle ownership; never reruns ambiguous work."""
        if self._closed or (self._worker is not None and not self._worker.done()):
            raise RuntimeError("recovery requires an idle open service")
        try:
            if self._bot_session is not None:
                # A fresh START grants no authority to replay queued work
                # from a lost controller or a previous stopped session.
                self._store.stop_unclaimed(now=self._now())
            for snapshot in self._store.recoverable():
                self._reconcile(snapshot)
        except Exception:
            self._failed = True
            raise RuntimeError("local command recovery failed") from None
        self._failed = False
        if self._bot_session is None:
            self._kick()

    async def wait_idle(self) -> None:
        if self._worker is not None:
            await asyncio.shield(self._worker)

    async def close(self) -> None:
        self._closed = True
        try:
            if self._bot_session is not None:
                self._store.stop_unclaimed(now=self._now())
            if self._active_key is not None and self._active_member is not None:
                self._store.stop(self._active_key, member_id=self._active_member, now=self._now())
        except Exception:
            self._failed = True
        finally:
            if self._active is not None:
                self._active.cancel()
            await self.wait_idle()
