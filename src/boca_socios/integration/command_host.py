"""Bounded synchronous host for one persistent local BETA command loop.

The private HTTP adapter supplies authorization and member scope. This module
has no listener, credentials, third-party transport or storage initialization.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import TimeoutError as FutureTimeoutError
from threading import Event, Lock, Thread
from typing import Any, TypeVar

from boca_socios.domain.policy import TicketIntent
from boca_socios.integration.beta import (
    BetaCoordinator,
    CommandCapacityError,
    CommandConflict,
    CommandSnapshot,
)

_Result = TypeVar("_Result")


class CommandResultUnknown(RuntimeError):
    """A request timed out; query its same command ID before deciding again."""


class BetaCommandHost:
    """Own a single event loop for command requests and startup recovery.

    A hosting process must hold exactly one instance and close it on shutdown.
    `BetaCoordinator.prepare_storage()` is a separate, explicit first-install
    action; opening this facade never creates or migrates a database.
    """

    def __init__(
        self,
        coordinator: BetaCoordinator,
        *,
        request_timeout_seconds: float = 5.0,
        startup_timeout_seconds: float = 10.0,
        shutdown_timeout_seconds: float = 35.0,
    ) -> None:
        for name, value in (
            ("request", request_timeout_seconds),
            ("startup", startup_timeout_seconds),
            ("shutdown", shutdown_timeout_seconds),
        ):
            if type(value) not in (int, float) or not 0 < value <= 60:
                raise ValueError(f"{name} timeout must be finite and in (0,60]")
        self._coordinator = coordinator
        self._request_timeout = float(request_timeout_seconds)
        self._startup_timeout = float(startup_timeout_seconds)
        self._shutdown_timeout = float(shutdown_timeout_seconds)
        self._loop = asyncio.new_event_loop()
        self._ready = Event()
        self._closed = False
        self._lock = Lock()
        self._thread = Thread(target=self._run, name="boca-local-command-loop", daemon=True)

    @classmethod
    def start(
        cls,
        coordinator: BetaCoordinator,
        *,
        request_timeout_seconds: float = 5.0,
        startup_timeout_seconds: float = 10.0,
        shutdown_timeout_seconds: float = 35.0,
    ) -> BetaCommandHost:
        """Recover under the caller's exclusive process ownership, then serve."""
        host = cls(
            coordinator,
            request_timeout_seconds=request_timeout_seconds,
            startup_timeout_seconds=startup_timeout_seconds,
            shutdown_timeout_seconds=shutdown_timeout_seconds,
        )
        host._thread.start()
        if not host._ready.wait(timeout=host._startup_timeout):
            host._terminate()
            raise RuntimeError("local command loop did not start")
        try:
            host._submit(coordinator.recover(), timeout=host._startup_timeout)
        except Exception:
            host.close()
            raise RuntimeError("local command recovery failed") from None
        return host

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                # The injected synthetic port must cooperate with cancellation.
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()
            asyncio.set_event_loop(None)

    def _submit(self, operation: Coroutine[Any, Any, _Result], *, timeout: float) -> _Result:
        with self._lock:
            if self._closed:
                operation.close()
                raise RuntimeError("local command host is closed")
            try:
                future = asyncio.run_coroutine_threadsafe(operation, self._loop)
            except RuntimeError:
                operation.close()
                raise RuntimeError("local command host is unavailable") from None
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            # Do not cancel a potentially committed local intent. The caller
            # must inspect the same canonical key before trying another action.
            raise CommandResultUnknown("local command result unknown; query the same ID") from None
        except (CommandConflict, CommandCapacityError, ValueError):
            raise
        except Exception:
            raise RuntimeError("local command unavailable") from None

    def begin(self, command_id: str, *, member_id: str, event_id: str) -> CommandSnapshot:
        return self._submit(
            self._coordinator.begin(command_id, TicketIntent(member_id, event_id)),
            timeout=self._request_timeout,
        )

    def status(self, command_id: str, *, member_id: str) -> CommandSnapshot | None:
        async def read() -> CommandSnapshot | None:
            return self._coordinator.status(command_id, member_id=member_id)

        return self._submit(read(), timeout=self._request_timeout)

    def stop(self, command_id: str, *, member_id: str) -> CommandSnapshot | None:
        return self._submit(
            self._coordinator.stop(command_id, member_id=member_id),
            timeout=self._request_timeout,
        )

    @property
    def failed(self) -> bool:
        return self._coordinator.failed or self._closed or not self._thread.is_alive()

    def _terminate(self) -> None:
        if self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=self._shutdown_timeout)
        else:
            self._loop.close()
        if self._thread.is_alive():
            raise RuntimeError("local command loop did not stop")

    def close(self) -> None:
        """Stop accepting work, cancel/join the worker, then join the loop."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        failure = False
        if self._thread.is_alive():
            try:
                future = asyncio.run_coroutine_threadsafe(self._coordinator.close(), self._loop)
                future.result(timeout=self._shutdown_timeout)
            except Exception:
                failure = True
        try:
            self._terminate()
        except RuntimeError:
            failure = True
        if failure:
            raise RuntimeError("local command shutdown incomplete") from None
