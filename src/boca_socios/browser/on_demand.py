"""Bounded one-shot bridge from the local coordinator to a synthetic page.

This adapter is inert until ``simulate_general_reservation`` is called. The
trusted page factory must run inside the *separate* UID 10002 browser worker
with a verified no-egress Docker network, and must close its Chromium context
on cancellation. This module neither starts Docker nor visits a URL. A
different approved host/Compose contract is required to connect that worker
to the BETA controller; importing this module does not activate Chromium.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from math import isfinite
from typing import cast

from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.browser.synthetic import PagePort, SyntheticTicketScenario
from boca_socios.browser.worker_health import (
    CGROUP,
    CPU_MILLI_LIMIT,
    MEMORY_LIMIT_BYTES,
    PIDS_LIMIT,
    WORKER_UID,
    WorkerBoundaryError,
    validate_worker_boundary,
)

__all__ = [
    "CGROUP",
    "CPU_MILLI_LIMIT",
    "MEMORY_LIMIT_BYTES",
    "PIDS_LIMIT",
    "WORKER_UID",
    "OnDemandSyntheticBrowser",
    "PageFactory",
    "WorkerBoundaryError",
    "validate_worker_boundary",
]

PageFactory = Callable[[], AbstractAsyncContextManager[PagePort]]


class OnDemandSyntheticBrowser:
    """One fake DOM journey at a time; no session, URL or login input.

    The coordinator owns the durable one-ticket ledger and stop/recovery.
    This is only a disposable page executor. There is no prelaunch, polling,
    timer, queue-position fabrication or direct website interaction.
    """

    def __init__(
        self,
        pages: PageFactory,
        *,
        boundary_check: Callable[[], None] = validate_worker_boundary,
        timeout_seconds: float = 15.0,
        teardown_seconds: float = 5.0,
    ) -> None:
        if (
            type(timeout_seconds) not in (int, float)
            or not isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 30
        ):
            raise ValueError("synthetic worker timeout must be finite and in (0,30]")
        if (
            type(teardown_seconds) not in (int, float)
            or not isfinite(teardown_seconds)
            or not 0 < teardown_seconds <= 5
        ):
            raise ValueError("synthetic teardown must be finite and in (0,5]")
        self._pages = pages
        self._check = boundary_check
        self._timeout = float(timeout_seconds)
        self._teardown = float(teardown_seconds)
        self._active: asyncio.Task[SimulationOutcome] | None = None
        self._closed = False

    async def simulate_general_reservation(self) -> SimulationOutcome:
        if self._closed:
            raise WorkerBoundaryError("worker_closed")
        if self._active is not None:
            raise WorkerBoundaryError("worker_busy")
        self._check()
        active = asyncio.current_task()
        if active is None:
            raise WorkerBoundaryError("worker_loop_unavailable")
        self._active = cast("asyncio.Task[SimulationOutcome]", active)
        try:
            async with asyncio.timeout(self._timeout) as deadline:
                async with self._pages() as page:
                    outcome = await SyntheticTicketScenario(page).simulate_general_reservation()
                # Context teardown can itself suppress CancelledError. A result
                # is not trustworthy until *after* teardown and its deadline.
                if deadline.expired():
                    raise TimeoutError("synthetic worker deadline expired")
                if self._closed:
                    raise WorkerBoundaryError("worker_closed")
                if active.cancelling():
                    # A context manager may swallow an external STOP/cancel.
                    # The coordinator must never observe late fake success.
                    raise asyncio.CancelledError
                if outcome is not SimulationOutcome.RESERVED_IN_SIMULATOR:
                    raise WorkerBoundaryError("worker_result_unverified")
                return outcome
        finally:
            self._active = None

    async def close(self) -> None:
        """Fence new work and cancel an active page, allowing bounded teardown."""
        self._closed = True
        active = self._active
        if active is None or active.done() or active is asyncio.current_task():
            return
        active.cancel()
        # wait_for() can exceed its timeout while waiting for a task that
        # suppresses cancellation. Isolated host cleanup must terminate the
        # disposable worker if this bounded join does not complete.
        _, pending = await asyncio.wait({active}, timeout=self._teardown)
        if pending:
            raise WorkerBoundaryError("worker_teardown_unverified") from None
