"""Opt-in, offline UID10002 AF_UNIX worker for the fixed fake DOM journey.

This is *not* a new deployed service or a controller entrypoint. The host
must separately prove --network none, an isolated container, a disposable
IPC volume, cgroup limits, immutable image and selective failure cleanup.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import sys
from collections.abc import Callable
from math import isfinite
from pathlib import Path
from time import monotonic
from typing import Protocol

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
from boca_socios.browser.on_demand import (
    OnDemandSyntheticBrowser,
    WorkerBoundaryError,
    validate_worker_boundary,
)
from boca_socios.browser.playwright_factory import isolated_playwright_page


class SyntheticExecutor(Protocol):
    async def simulate_general_reservation(self) -> SimulationOutcome: ...

    async def close(self) -> None: ...


def validate_no_egress_namespace() -> None:
    """A worker with any non-loopback interface cannot start Chromium.

    This is a local additional guard; only the independently reviewed Docker
    --network none isolation can establish the complete OS boundary.
    """
    try:
        interfaces = socket.if_nameindex()
    except OSError:
        raise SyntheticIPCError("worker_network_unverified") from None
    if len(interfaces) != 1 or interfaces[0][1] != "lo" or interfaces[0][0] < 1:
        raise SyntheticIPCError("worker_network_unverified")


def _check_worker_boundary() -> None:
    validate_worker_boundary()
    validate_no_egress_namespace()


def _seconds(value: float, maximum: float) -> float:
    if type(value) not in (int, float) or not isfinite(value) or not 0 < value <= maximum:
        raise ValueError("IPC deadline must be finite and bounded")
    return float(value)


class UnixSyntheticWorker:
    """Idle local IPC listener; only a valid authenticated request opens a page.

    At most one accepted request and one Chromium journey are in progress.
    Any uncooperative cancellation permanently fences this worker; a future
    protected host lifecycle must kill and remove its disposable container.
    """

    def __init__(
        self,
        browser: SyntheticExecutor,
        *,
        socket_path: Path = SOCKET_PATH,
        boundary_check: Callable[[], None] = _check_worker_boundary,
        request_seconds: float = 2.0,
        operation_seconds: float = 20.0,
        teardown_seconds: float = 5.0,
    ) -> None:
        self._browser = browser
        self._path = socket_path
        self._boundary_check = boundary_check
        self._request_seconds = _seconds(request_seconds, 2.0)
        self._operation_seconds = _seconds(operation_seconds, 20.0)
        self._teardown_seconds = _seconds(teardown_seconds, 5.0)
        self._server: asyncio.AbstractServer | None = None
        self._owned_socket: tuple[int, int] | None = None
        self._active: asyncio.Task[SimulationOutcome] | None = None
        self._busy = False
        self._closed = False
        self._poisoned = asyncio.Event()

    async def start(self) -> None:
        """Do not create directories or overwrite even a stale socket."""
        if self._closed or self._server is not None:
            raise SyntheticIPCError("worker_lifecycle_unverified")
        self._boundary_check()
        if self._path.name != SOCKET_PATH.name:
            raise SyntheticIPCError("ipc_path_unverified")
        validate_socket_directory(self._path.parent, uid=WORKER_UID)
        try:
            if os.listdir(self._path.parent):
                raise SyntheticIPCError("ipc_mount_not_empty")
        except OSError:
            raise SyntheticIPCError("ipc_mount_unverified") from None
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.setblocking(False)
        try:
            previous = os.umask(0o155)  # AF_UNIX path starts at exact mode 0622.
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
            # A partial bind may have left a socket. Preserve it as uncertain
            # state for a reviewed disposable-volume cleanup, never unlink it.
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
    def _consume(task: asyncio.Task[SimulationOutcome]) -> None:
        # Do not log third-party exception text or a late synthetic result.
        try:
            task.result()
        except (Exception, asyncio.CancelledError):
            return

    async def _run_synthetic(self) -> bytes:
        self._boundary_check()
        active = asyncio.create_task(self._browser.simulate_general_reservation())
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
            return NO_GO
        try:
            if completed and active.result() is SimulationOutcome.RESERVED_IN_SIMULATOR:
                return SUCCESS
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
                # Drain one *bounded* frame before rejecting: closing a UNIX
                # stream with unread data can reset the peer and lose BUSY.
                try:
                    await self._read_request(reader)
                except (SyntheticIPCError, OSError, TimeoutError):
                    await self._respond(writer, NO_GO)
                else:
                    await self._respond(writer, BUSY)
                return
            self._busy = True  # No await between test and assignment.
            accepted = True
            try:
                await self._read_request(reader)
                # Reading the complete frame yields to the event loop. STOP
                # may have closed this worker while the peer was still
                # writing; never launch a browser for that stale request.
                if self._closed or self._poisoned.is_set():
                    raise SyntheticIPCError("worker_closed")
                deadline = monotonic() + self._operation_seconds
                response = await self._run_synthetic()
                # Last non-await boundary before queueing the reply. A STOP,
                # cancellation or elapsed deadline during teardown can never
                # be upgraded to success by a late synthetic task result.
                current = asyncio.current_task()
                if response == SUCCESS and (
                    self._closed
                    or self._poisoned.is_set()
                    or monotonic() >= deadline
                    or current is None
                    or current.cancelling()
                ):
                    response = NO_GO
            except (SyntheticIPCError, WorkerBoundaryError, OSError, TimeoutError, ValueError):
                response = NO_GO
            await self._respond(writer, response)
        except (SyntheticIPCError, OSError, TimeoutError, ConnectionError):
            # Never return a successful outcome or an arbitrary exception body.
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
        """Close only the socket inode created by this exact worker instance."""
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
        closing = asyncio.create_task(self._browser.close())
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


async def _run_server() -> None:
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, stopping.set)
    loop.add_signal_handler(signal.SIGINT, stopping.set)
    worker = UnixSyntheticWorker(OnDemandSyntheticBrowser(isolated_playwright_page))
    try:
        await worker.serve_until(stopping)
    except SyntheticIPCError as exc:
        if str(exc) == "worker_teardown_unverified":
            # asyncio.run() would otherwise wait indefinitely for an
            # uncooperative Chromium task. Only this disposable UID10002
            # worker process is terminated; the host must inventory/clean
            # its own positively identified artifacts before a new attempt.
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
