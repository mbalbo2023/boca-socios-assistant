"""One owner-started, bounded IPC observation loop; no network client or ticket flow."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from threading import Event, Lock, Thread
from time import monotonic
from typing import TYPE_CHECKING, Protocol

from boca_socios.panel.lifecycle_intents import (
    AUTOMATIC_CHECK_TERMINAL,
    AUTOMATIC_CHECK_WAITING,
    LifecycleConflict,
    LifecycleIntentStore,
    LifecycleStorageUnavailable,
    canonical_operation_id,
)

if TYPE_CHECKING:
    from boca_socios.browser.queue_page_observation import QueuePageObservation


class ObservationMonitor(Protocol):
    def mark_checking(self) -> None: ...

    def observe_global(self, observation: QueuePageObservation) -> None: ...


class AutomaticObservationSession:
    """Begin only from a new CLAIMED start, and observe only after its APPLIED receipt.

    Polling retains the worker's existing session. Every exchange is bounded by
    the IPC client; only an active queue/prefila permits another passive sample.
    A controller restart never silently resumes a historical activation.
    """

    def __init__(
        self,
        *,
        ledger: LifecycleIntentStore,
        observe: Callable[[], Awaitable[QueuePageObservation]],
        monitor: ObservationMonitor,
        wake: Callable[[str], None],
    ) -> None:
        self._ledger = ledger
        self._observe = observe
        self._monitor = monitor
        self._wake = wake
        self._lock = Lock()
        self._cancel = Event()
        self._thread: Thread | None = None
        self._start_id: str | None = None
        self._closed = False

    def _matches(self, start_id: str, status: str) -> bool:
        state = self._ledger.current()
        return bool(
            state is not None
            and state.operation_id == start_id
            and state.on_demand
            and (state.component, state.target, state.status) == ("bot", "start", status)
        )

    def start(self, start_id: str) -> None:
        canonical_operation_id(start_id)
        with self._lock:
            if self._closed or not self._matches(start_id, "CLAIMED"):
                raise RuntimeError("automatic observation requires a new claimed owner start")
            if self._thread is not None and self._thread.is_alive():
                if self._start_id == start_id:
                    return
                self._cancel.set()
                self._thread.join(timeout=5)
                if self._thread.is_alive():
                    raise RuntimeError("previous observation has not stopped")
            self._cancel = Event()
            self._start_id = start_id
            self._ledger.record_automatic_check(start_id, "CHECKING")
            self._thread = Thread(
                target=self._await_applied,
                args=(start_id,),
                name="boca-owner-queue-observation",
                daemon=True,
            )
            self._thread.start()

    def _await_applied(self, start_id: str) -> None:
        deadline = monotonic() + 30
        try:
            while not self._cancel.is_set() and monotonic() < deadline:
                current = self._ledger.current()
                if (
                    current is None
                    or current.operation_id != start_id
                    or not current.on_demand
                    or (current.component, current.target) != ("bot", "start")
                ):
                    return
                if current.status == "APPLIED":
                    self.run_confirmed(start_id)
                    return
                if current.status != "CLAIMED":
                    return
                self._cancel.wait(0.1)
        except (LifecycleStorageUnavailable, LifecycleConflict):
            # A missing host receipt is not authority to navigate or fabricate STOP.
            return

    def run_confirmed(
        self,
        start_id: str,
        *,
        wait: Callable[[float], bool] | None = None,
    ) -> None:
        """Execute the receipt-bound loop, also usable by the offline contract harness."""
        canonical_operation_id(start_id)
        pause = self._cancel.wait if wait is None else wait

        async def poll() -> None:
            while not self._cancel.is_set() and self._matches(start_id, "APPLIED"):
                self._ledger.record_automatic_check(start_id, "CHECKING")
                self._monitor.mark_checking()
                try:
                    observation = await self._observe()
                    if (
                        observation.outcome
                        not in AUTOMATIC_CHECK_WAITING | AUTOMATIC_CHECK_TERMINAL
                    ):
                        raise ValueError("unrecognized worker observation")
                except Exception:
                    from boca_socios.browser.queue_page_observation import (
                        parse_queue_page_observation,
                    )

                    observation = parse_queue_page_observation(
                        final_url="",
                        queue_model=None,
                        markers=frozenset(),
                        observed_at=datetime.now(UTC),
                        check_failed=True,
                    )
                # STOP can supersede this start while the bounded IPC call runs.
                if self._cancel.is_set() or not self._matches(start_id, "APPLIED"):
                    return
                self._monitor.observe_global(observation)
                self._ledger.record_automatic_check(start_id, observation.outcome)
                if observation.outcome in AUTOMATIC_CHECK_TERMINAL:
                    stop = self._ledger.request_work_stop(start_id)
                    if stop is not None and stop.status == "REQUESTED":
                        try:
                            self._wake(stop.operation_id)
                        except OSError:
                            # Same durable UUID remains available for safe redelivery.
                            pass
                    return
                if pause(5.0):
                    return

        try:
            asyncio.run(poll())
        except (LifecycleStorageUnavailable, LifecycleConflict):
            return

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._cancel.set()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=35)
            if thread.is_alive():
                raise RuntimeError("automatic observation shutdown unverified")
