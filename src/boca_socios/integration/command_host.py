"""Bounded synchronous host for one persistent local BETA command loop.

The private HTTP adapter supplies authorization and member scope. This module
has no listener, credentials, third-party transport or storage initialization.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from concurrent.futures import TimeoutError as FutureTimeoutError
from threading import Event, Lock, Thread
from typing import Any, Literal, TypeVar

from boca_socios.domain.policy import TicketIntent
from boca_socios.integration.beta import (
    BetaCoordinator,
    CommandCapacityError,
    CommandConflict,
    CommandSnapshot,
)

_Result = TypeVar("_Result")
EngineState = Literal["starting", "running", "stopping", "stopped", "failed", "closed"]


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
        coordinator_factory: Callable[[], BetaCoordinator] | None = None,
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
        self._coordinator_factory = coordinator_factory
        self._request_timeout = float(request_timeout_seconds)
        self._startup_timeout = float(startup_timeout_seconds)
        self._shutdown_timeout = float(shutdown_timeout_seconds)
        self._loop = asyncio.new_event_loop()
        self._ready = Event()
        self._closed = False
        self._lock = Lock()
        self._lifecycle_lock = Lock()
        self._engine_state: EngineState = "starting"
        self._thread = Thread(target=self._run, name="boca-local-command-loop", daemon=True)

    @classmethod
    def start(
        cls,
        coordinator: BetaCoordinator,
        *,
        coordinator_factory: Callable[[], BetaCoordinator] | None = None,
        request_timeout_seconds: float = 5.0,
        startup_timeout_seconds: float = 10.0,
        shutdown_timeout_seconds: float = 35.0,
    ) -> BetaCommandHost:
        """Recover under the caller's exclusive process ownership, then serve."""
        host = cls(
            coordinator,
            coordinator_factory=coordinator_factory,
            request_timeout_seconds=request_timeout_seconds,
            startup_timeout_seconds=startup_timeout_seconds,
            shutdown_timeout_seconds=shutdown_timeout_seconds,
        )
        host._thread.start()
        if not host._ready.wait(timeout=host._startup_timeout):
            host._terminate()
            raise RuntimeError("local command loop did not start")
        try:
            host._submit(lambda: coordinator.recover(), timeout=host._startup_timeout, startup=True)
        except Exception:
            host.close()
            raise RuntimeError("local command recovery failed") from None
        with host._lock:
            host._engine_state = "running"
        return host

    @classmethod
    def start_stopped(
        cls,
        coordinator: BetaCoordinator,
        *,
        coordinator_factory: Callable[[], BetaCoordinator],
        request_timeout_seconds: float = 5.0,
        startup_timeout_seconds: float = 10.0,
        shutdown_timeout_seconds: float = 35.0,
    ) -> BetaCommandHost:
        """Restore an attested owner STOP without creating a running thread.

        Reboot recovery must not start a loop and then stop it: that would
        replay durable commands before the trusted host STOP is honored.
        The future explicit `start_engine()` creates a fresh loop and invokes
        the normal recovery only after another protected owner instruction.
        """
        if not callable(coordinator_factory):
            raise ValueError("stopped engine requires a restart factory")
        host = cls(
            coordinator,
            coordinator_factory=coordinator_factory,
            request_timeout_seconds=request_timeout_seconds,
            startup_timeout_seconds=startup_timeout_seconds,
            shutdown_timeout_seconds=shutdown_timeout_seconds,
        )
        # __init__ allocates only an inert event-loop object and Thread
        # object. Close the unused loop before a later explicit START replaces
        # it, so STOP-on-reboot leaks neither threads nor loop descriptors.
        host._loop.close()
        with host._lock:
            host._engine_state = "stopped"
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

    def _submit(
        self,
        make_operation: Callable[[], Coroutine[Any, Any, _Result]],
        *,
        timeout: float,
        startup: bool = False,
    ) -> _Result:
        with self._lock:
            if self._closed:
                raise RuntimeError("local command host is closed")
            if self._engine_state != ("starting" if startup else "running"):
                raise RuntimeError("local command engine is stopped or unavailable")
            operation = make_operation()
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
            lambda: self._coordinator.begin(command_id, TicketIntent(member_id, event_id)),
            timeout=self._request_timeout,
        )

    def status(self, command_id: str, *, member_id: str) -> CommandSnapshot | None:
        with self._lock:
            # Durable status may be read with no worker thread; it never
            # enqueues or replays synthetic commands.
            if self._engine_state == "stopped" and not self._closed:
                return self._coordinator.status(command_id, member_id=member_id)

        async def read() -> CommandSnapshot | None:
            return self._coordinator.status(command_id, member_id=member_id)

        return self._submit(read, timeout=self._request_timeout)

    def stop(self, command_id: str, *, member_id: str) -> CommandSnapshot | None:
        return self._submit(
            lambda: self._coordinator.stop(command_id, member_id=member_id),
            timeout=self._request_timeout,
        )

    @property
    def failed(self) -> bool:
        with self._lock:
            return (
                self._engine_state != "running"
                or self._coordinator.failed
                or not self._thread.is_alive()
            )

    @property
    def engine_running(self) -> bool:
        """Actual live command loop, not the separate panel intake control."""
        with self._lock:
            return (
                self._engine_state == "running"
                and self._thread.is_alive()
                and not self._coordinator.failed
            )

    @property
    def engine_stopped(self) -> bool:
        with self._lock:
            return self._engine_state == "stopped" and not self._thread.is_alive()

    def _shutdown_coordinator(self) -> None:
        """Cancel/drain the real loop before reporting an engine as stopped."""
        if not self._thread.is_alive():
            raise RuntimeError("local command loop stopped without a receipt")
        future = asyncio.run_coroutine_threadsafe(self._coordinator.close(), self._loop)
        future.result(timeout=self._shutdown_timeout)
        self._terminate()

    def stop_engine(self) -> bool:
        """Stop the synthetic command worker, not the authenticated HTTP panel."""
        with self._lifecycle_lock:
            with self._lock:
                if self._closed:
                    raise RuntimeError("local command host is closed")
                if self._coordinator_factory is None:
                    raise RuntimeError("local command engine restart factory unavailable")
                if self._engine_state == "stopped":
                    return False
                if self._engine_state != "running" or not self._thread.is_alive():
                    raise RuntimeError("local command engine shutdown state is unknown")
                self._engine_state = "stopping"
            try:
                self._shutdown_coordinator()
            except Exception:
                with self._lock:
                    self._engine_state = "failed"
                raise RuntimeError("local command engine stop unverified") from None
            with self._lock:
                self._engine_state = "stopped"
            return True

    def start_engine(self) -> bool:
        """Create a new event loop and recover durable synthetic intents."""
        with self._lifecycle_lock:
            with self._lock:
                if self._closed:
                    raise RuntimeError("local command host is closed")
                if self._engine_state == "running" and self._thread.is_alive():
                    return False
                if self._engine_state != "stopped" or self._coordinator_factory is None:
                    raise RuntimeError("local command engine start state unavailable")
                self._engine_state = "starting"
            try:
                new_coordinator = self._coordinator_factory()
                if not isinstance(new_coordinator, BetaCoordinator):
                    raise RuntimeError("local command engine factory produced an invalid worker")
                self._coordinator = new_coordinator
                self._loop = asyncio.new_event_loop()
                self._ready = Event()
                self._thread = Thread(target=self._run, name="boca-local-command-loop", daemon=True)
                self._thread.start()
                if not self._ready.wait(timeout=self._startup_timeout):
                    raise RuntimeError("local command engine loop did not start")
                self._submit(
                    lambda: new_coordinator.recover(),
                    timeout=self._startup_timeout,
                    startup=True,
                )
            except Exception:
                try:
                    self._terminate()
                except RuntimeError:
                    pass
                with self._lock:
                    self._engine_state = "failed"
                raise RuntimeError("local command engine start unverified") from None
            with self._lock:
                self._engine_state = "running"
            return True

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
        with self._lifecycle_lock:
            with self._lock:
                if self._closed:
                    return
                self._closed = True
                was_stopped = self._engine_state == "stopped"
                self._engine_state = "closed"
            if was_stopped:
                return
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
