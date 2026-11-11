"""Bounded AF_UNIX adapter for a disposable Boca *simulation* worker.

This integration boundary never imports the two owner-controlled navigation
modules and cannot navigate a website by default. A reviewed offline executor
can be injected to prove the controller's fixed IPC contract. The default
entrypoint serves the health/peer transport but rejects all work with NO_GO.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import sys
from collections.abc import Callable
from enum import StrEnum
from importlib import import_module
from math import isfinite
from pathlib import Path
from time import monotonic
from typing import Protocol

from boca_socios.browser.activity_events import reset_chromium_activity
from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.browser.ipc_protocol import (
    BUSY,
    CONTROLLER_UID,
    MAX_FRAME_BYTES,
    NO_GO,
    REQUEST,
    SOCKET_PATH,
    SUCCESS,
    WORKER_UID,
    SyntheticIPCError,
    framed,
    read_frame,
    socket_identity,
    validate_socket_directory,
    verify_peer,
)
from boca_socios.browser.worker_health import WorkerBoundaryError, validate_worker_boundary


class ObservationStatus(StrEnum):
    """Redacted browser observation, NEVER evidence of a simulated reservation.

    The owner-controlled navigation engine is deliberately not loaded here.
    These states carry neither a queue token nor the observed destination and
    must not be promoted to the protocol's RESERVED_IN_SIMULATOR response.
    """

    TOKEN_OBSERVED = "token_observed"  # noqa: S105 - fixed category, never token contents
    TOKEN_ABSENT = "token_absent"  # noqa: S105 - fixed category, never token contents
    OBSERVATION_FAILED = "observation_failed"


class SyntheticExecutor(Protocol):
    """Small dependency-injection boundary; no URL or ticket data cross IPC."""

    async def simulate_general_reservation(self) -> SimulationOutcome | ObservationStatus: ...

    async def close(self) -> None: ...


class OfflineNoGoExecutor:
    """Safe default: a healthy listener does not mean navigation is enabled."""

    async def simulate_general_reservation(self) -> SimulationOutcome:
        raise SyntheticIPCError("worker_executor_not_configured")

    async def close(self) -> None:
        return


def _check_worker_boundary() -> None:
    """Require the Boca worker identity, limits and isolated egress interface set."""
    validate_worker_boundary()
    try:
        interfaces = socket.if_nameindex()
    except OSError:
        raise SyntheticIPCError("worker_network_unverified") from None
    if len(interfaces) != 2 or {name for index, name in interfaces if index > 0} != {
        "lo",
        "eth0",
    }:
        raise SyntheticIPCError("worker_network_unverified")


def _seconds(value: float, maximum: float) -> float:
    if type(value) not in (int, float) or not isfinite(value) or not 0 < value <= maximum:
        raise ValueError("IPC deadline must be finite and bounded")
    return float(value)


class UnixSyntheticWorker:
    """One authenticated synthetic command at a time with bounded STOP.

    Socket ownership and peer credentials are kernel-checked, not trusted from
    payloads. An uncooperative executor permanently poisons this disposable
    worker so the protected host lifecycle can terminate its exact container.
    """

    def __init__(
        self,
        executor: SyntheticExecutor | None = None,
        *,
        socket_path: Path = SOCKET_PATH,
        boundary_check: Callable[[], None] = _check_worker_boundary,
        request_seconds: float = 2.0,
        operation_seconds: float = 20.0,
        teardown_seconds: float = 5.0,
        on_observation: Callable[[ObservationStatus], None] | None = None,
    ) -> None:
        self._executor = OfflineNoGoExecutor() if executor is None else executor
        self._on_observation = on_observation
        self._path = socket_path
        self._boundary_check = boundary_check
        self._request_seconds = _seconds(request_seconds, 2.0)
        self._operation_seconds = _seconds(operation_seconds, 20.0)
        self._teardown_seconds = _seconds(teardown_seconds, 5.0)
        self._server: asyncio.AbstractServer | None = None
        self._owned_socket: tuple[int, int] | None = None
        self._active: asyncio.Task[SimulationOutcome | ObservationStatus] | None = None
        self._busy = False
        self._closed = False
        self._poisoned = asyncio.Event()
        self._stop_requested: asyncio.Event | None = None

    def _stopping(self) -> bool:
        return (
            self._closed
            or self._poisoned.is_set()
            or (self._stop_requested is not None and self._stop_requested.is_set())
        )

    async def start(self) -> None:
        """Bind only inside a verified, empty worker-owned directory."""
        if self._closed or self._server is not None:
            raise SyntheticIPCError("worker_lifecycle_unverified")
        self._boundary_check()
        if self._path.name != SOCKET_PATH.name:
            raise SyntheticIPCError("ipc_path_unverified")
        validate_socket_directory(self._path.parent, uid=WORKER_UID)
        # A previous worker may have left fixed-category activity records in
        # the persistent IPC volume. Retire only verified telemetry inodes;
        # any unknown file or stale socket still fails closed before bind.
        reset_chromium_activity(path=self._path.with_name("chromium-events.jsonl"))
        try:
            if os.listdir(self._path.parent):
                raise SyntheticIPCError("ipc_mount_not_empty")
        except OSError:
            raise SyntheticIPCError("ipc_mount_unverified") from None

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.setblocking(False)
        try:
            previous = os.umask(0o155)  # 0777 & ~0155 = 0622 for Unix sockets.
            try:
                listener.bind(str(self._path))
            finally:
                os.umask(previous)
            self._owned_socket = socket_identity(self._path, uid=WORKER_UID)
            listener.listen(1)
            self._server = await asyncio.start_unix_server(
                self._handle, sock=listener, start_serving=False, limit=MAX_FRAME_BYTES
            )
            await self._server.start_serving()
        except BaseException:
            listener.close()
            # Preserve any uncertain socket inode for selective host cleanup.
            self._closed = True
            raise

    @staticmethod
    async def _respond(writer: asyncio.StreamWriter, payload: bytes) -> None:
        writer.write(framed(payload))
        await asyncio.wait_for(writer.drain(), timeout=1.0)

    async def _read_request(self, reader: asyncio.StreamReader) -> None:
        async with asyncio.timeout(self._request_seconds):
            if await read_frame(reader) != REQUEST or await reader.read(1) != b"":
                raise SyntheticIPCError("ipc_request_unverified")

    @staticmethod
    def _consume(task: asyncio.Task[SimulationOutcome | ObservationStatus]) -> None:
        # No exception text, navigation output or late result is logged.
        try:
            task.result()
        except (Exception, asyncio.CancelledError):
            return

    async def _run_synthetic(self) -> bytes:
        self._boundary_check()
        active = asyncio.create_task(self._executor.simulate_general_reservation())
        self._active = active
        active.add_done_callback(self._consume)
        completed, pending = await asyncio.wait({active}, timeout=self._operation_seconds)
        if pending:
            active.cancel()
            completed, pending = await asyncio.wait({active}, timeout=self._teardown_seconds)
            if pending:
                self._poisoned.set()
                if self._server is not None:
                    self._server.close()
            return NO_GO
        try:
            result = active.result()
            if self._stopping() or active.cancelling():
                return NO_GO
            if result is SimulationOutcome.RESERVED_IN_SIMULATOR:
                return SUCCESS
            if isinstance(result, ObservationStatus) and self._on_observation is not None:
                # Only the fixed category crosses this local callback; no raw
                # tokens, URLs, engine results or private exception strings.
                self._on_observation(result)
        except SyntheticIPCError as exc:
            if str(exc) == "offline_fixture_teardown_unverified":
                # The executor could not prove that Chromium was closed. The
                # disposable process must stop accepting work and exit through
                # serve_until's existing poisoned-worker termination path.
                self._poisoned.set()
                if self._server is not None:
                    self._server.close()
            return NO_GO
        except (Exception, asyncio.CancelledError):
            return NO_GO
        return NO_GO

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        accepted = False
        try:
            verify_peer(writer, uid=CONTROLLER_UID, gid=CONTROLLER_UID)
            if self._closed or self._poisoned.is_set():
                return
            if self._busy:
                # Drain one bounded request before replying; unread stream data
                # can reset the Unix peer before BUSY is delivered.
                try:
                    await self._read_request(reader)
                except (SyntheticIPCError, OSError, TimeoutError):
                    await self._respond(writer, NO_GO)
                else:
                    await self._respond(writer, BUSY)
                return
            self._busy = True
            accepted = True
            try:
                await self._read_request(reader)
                # STOP may occur during partial-frame I/O. Never start a job
                # after that await if this server has already been closed.
                if self._stopping():
                    raise SyntheticIPCError("worker_closed")
                deadline = monotonic() + self._operation_seconds
                response = await self._run_synthetic()
                task = asyncio.current_task()
                if response == SUCCESS and (
                    self._stopping() or monotonic() >= deadline or task is None or task.cancelling()
                ):
                    response = NO_GO
            except (SyntheticIPCError, WorkerBoundaryError, OSError, TimeoutError, ValueError):
                response = NO_GO
            await self._respond(writer, response)
        except (SyntheticIPCError, OSError, TimeoutError, ConnectionError):
            return
        finally:
            if accepted:
                self._busy = False
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=0.5)
            except (OSError, TimeoutError):
                pass

    async def close(self) -> None:
        """Close only the owned socket; poison on uncooperative teardown."""
        self._closed = True
        deadline = monotonic() + self._teardown_seconds
        if self._server is not None:
            self._server.close()
        active = self._active
        if active is not None and not active.done():
            active.cancel()
            _, still_running = await asyncio.wait(
                {active}, timeout=max(0.0, deadline - monotonic())
            )
            if still_running:
                self._poisoned.set()
                raise SyntheticIPCError("worker_teardown_unverified")
        if self._server is not None:
            closed_server = asyncio.create_task(self._server.wait_closed())
            _, unfinished_server = await asyncio.wait(
                {closed_server}, timeout=max(0.0, deadline - monotonic())
            )
            if unfinished_server:
                closed_server.cancel()
                self._poisoned.set()
                raise SyntheticIPCError("worker_teardown_unverified")
            closed_server.result()
            self._server = None
        closing = asyncio.create_task(self._executor.close())
        completed, unfinished_close = await asyncio.wait(
            {closing}, timeout=max(0.0, deadline - monotonic())
        )
        if unfinished_close:
            closing.cancel()
            self._poisoned.set()
            raise SyntheticIPCError("worker_teardown_unverified")
        try:
            if completed:
                closing.result()
        except (Exception, asyncio.CancelledError):
            self._poisoned.set()
            raise SyntheticIPCError("worker_teardown_unverified") from None
        if self._owned_socket is not None:
            if socket_identity(self._path, uid=WORKER_UID) != self._owned_socket:
                raise SyntheticIPCError("ipc_socket_changed")
            os.unlink(self._path)
            self._owned_socket = None

    async def serve_until(self, stopping: asyncio.Event) -> None:
        self._stop_requested = stopping
        if stopping.is_set():
            # A STOP already accepted by the demand supervisor may not
            # briefly reopen a listener or dispatch an executor call.
            await self.close()
            return
        await self.start()
        stopped = asyncio.create_task(stopping.wait())
        poisoned = asyncio.create_task(self._poisoned.wait())
        try:
            done, pending = await asyncio.wait(
                {stopped, poisoned}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            if poisoned in done:
                raise SyntheticIPCError("worker_teardown_unverified")
        finally:
            await self.close()


def _read_worker_site_url() -> str:
    """Read only the destination-only verified mount before accepting work."""
    runtime = import_module("boca_socios.browser.site_url_runtime")
    try:
        destination = runtime.read_site_url(runtime.RUNTIME_SITE_URL_PATH)
        if not isinstance(destination, str):
            raise SyntheticIPCError("site_url_not_ready")
        return destination
    except (OSError, ValueError, RuntimeError):
        # Do not include URL, file contents, or underlying error in a log.
        raise SyntheticIPCError("site_url_not_ready") from None


async def _run_server(
    executor_factory: Callable[[str], SyntheticExecutor] | None = None,
) -> None:
    site_url = _read_worker_site_url()
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, stopping.set)
    loop.add_signal_handler(signal.SIGINT, stopping.set)
    # The default remains transport-only. A reviewed offline factory may be
    # injected for simulation tests; the legacy browser orchestrator is not
    # silently treated as a reservation simulator.
    executor = OfflineNoGoExecutor() if executor_factory is None else executor_factory(site_url)
    worker = UnixSyntheticWorker(executor)
    try:
        await worker.serve_until(stopping)
    except SyntheticIPCError as exc:
        if str(exc) == "worker_teardown_unverified":
            # Only the disposable UID10002 worker itself; no other process.
            os._exit(70)
        raise


def main() -> int:
    try:
        asyncio.run(_run_server())
    except (SyntheticIPCError, WorkerBoundaryError, OSError):
        print("BOCA_SYNTHETIC_IPC state=NO_GO", file=sys.stderr)
        return 1
    print("BOCA_SYNTHETIC_IPC state=STOPPED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
