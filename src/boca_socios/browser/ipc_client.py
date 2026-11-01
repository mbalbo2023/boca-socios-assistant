"""Inert UID10001 client adapter for one fixed offline Chromium command.

Inject ``UnixSyntheticBrowser`` explicitly as the existing SyntheticBrowserPort.
Importing it opens no socket, starts no worker and changes no BETA defaults.
"""

from __future__ import annotations

import asyncio
import os
from math import isfinite
from pathlib import Path
from threading import Lock
from time import monotonic

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
    verify_peer,
)


def _check_controller_identity() -> None:
    if os.geteuid() != CONTROLLER_UID or os.getegid() != CONTROLLER_UID:
        raise SyntheticIPCError("controller_identity_unverified")


class UnixSyntheticBrowser:
    """One local synthetic call at a time; the coordinator retains durable ownership.

    The only command is a constant without member/event identifiers or URLs.
    SO_PEERCRED and socket metadata are checked before trusting the response.
    An interrupted invocation is never turned into simulated success.
    """

    def __init__(
        self,
        *,
        socket_path: Path = SOCKET_PATH,
        timeout_seconds: float = 25.0,
    ) -> None:
        if (
            type(timeout_seconds) not in (int, float)
            or not isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 30
        ):
            raise ValueError("IPC timeout must be finite and in (0,30]")
        self._path = socket_path
        self._timeout = float(timeout_seconds)
        self._gate = Lock()
        self._closed = False
        self._active: asyncio.Task[SimulationOutcome] | None = None

    async def simulate_general_reservation(self) -> SimulationOutcome:
        active = asyncio.current_task()
        if active is None:
            raise SyntheticIPCError("client_loop_unavailable")
        with self._gate:
            if self._closed:
                raise SyntheticIPCError("client_closed")
            if self._active is not None:
                raise SyntheticIPCError("client_busy")
            self._active = active
        deadline = monotonic() + self._timeout
        writer: asyncio.StreamWriter | None = None
        success = False
        try:
            _check_controller_identity()
            original = socket_identity(self._path, uid=WORKER_UID)
            try:
                async with asyncio.timeout(self._timeout):
                    reader, writer = await asyncio.open_unix_connection(
                        path=str(self._path), limit=MAX_FRAME_BYTES
                    )
                    verify_peer(writer, uid=WORKER_UID, gid=WORKER_UID)
                    if socket_identity(self._path, uid=WORKER_UID) != original:
                        raise SyntheticIPCError("ipc_socket_changed")
                    writer.write(framed(REQUEST))
                    await writer.drain()
                    if not writer.can_write_eof():
                        raise SyntheticIPCError("ipc_half_close_unavailable")
                    writer.write_eof()
                    reply = await read_frame(reader)
                    if await reader.read(1) != b"":
                        raise SyntheticIPCError("ipc_response_unverified")
                    if reply == SUCCESS:
                        success = True
                    elif reply == BUSY:
                        raise SyntheticIPCError("worker_busy")
                    elif reply == NO_GO:
                        raise SyntheticIPCError("worker_no_go")
                    else:
                        raise SyntheticIPCError("ipc_response_unverified")
                    # Close is part of acceptance, before inspecting lifecycle
                    # fences. A slow or cancellation-suppressing close may NOT
                    # turn a stopped/expired call into a late success.
                    writer.close()
                    closed = asyncio.create_task(writer.wait_closed())
                    done, pending = await asyncio.wait({closed}, timeout=0.5)
                    if pending:
                        closed.cancel()
                        raise SyntheticIPCError("ipc_close_unverified")
                    closed.result()
                    writer = None
            except TimeoutError:
                raise SyntheticIPCError("worker_timeout") from None
            except (OSError, ConnectionError):
                raise SyntheticIPCError("ipc_unavailable") from None
        finally:
            if writer is not None:
                writer.close()  # Synchronous teardown; do not await after gate release.
            with self._gate:
                self._active = None
        # No further await after this final gate. Even a swallowed task
        # cancellation or timeout cannot authorize a late synthetic success.
        with self._gate:
            if not success or self._closed or active.cancelling() or monotonic() >= deadline:
                raise SyntheticIPCError("client_closed_or_expired")
            return SimulationOutcome.RESERVED_IN_SIMULATOR

    async def close(self) -> None:
        """Fence results and bound cancellation; never launch or stop containers."""
        with self._gate:
            self._closed = True
            active = self._active
        if active is None or active.done() or active is asyncio.current_task():
            return
        active.get_loop().call_soon_threadsafe(active.cancel)
        _, pending = await asyncio.wait({active}, timeout=1.0)
        if pending:
            raise SyntheticIPCError("client_teardown_unverified")
