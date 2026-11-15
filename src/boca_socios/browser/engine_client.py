"""Thread-safe scoped client using the existing peer-checked private transport.

Authentication can run in the controller's existing helper thread/event loop.
STOP uses its own connection and never needs that loop to release a wire gate.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from math import isfinite
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import cast

from boca_socios.browser.boca_auth_protocol import BocaAuthReadiness, BocaAuthReply, BocaAuthRequest
from boca_socios.browser.engine_protocol import (
    CloseScope,
    EngineIdentity,
    EngineReply,
    EngineRequest,
    SessionInspection,
)
from boca_socios.browser.ipc_client import UnixSyntheticBrowser
from boca_socios.browser.ipc_protocol import ENGINE_SESSION, SOCKET_PATH, SyntheticIPCError
from boca_socios.browser.queue_page_observation import QueuePageObservation


class UnixEngineSession:
    def __init__(
        self,
        identity: EngineIdentity,
        *,
        socket_path: Path = SOCKET_PATH,
        timeout_seconds: float = 25.0,
    ) -> None:
        if not isinstance(identity, EngineIdentity):
            raise ValueError("engine identity required")
        if (
            type(timeout_seconds) not in (int, float)
            or not isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 30
        ):
            raise ValueError("engine IPC timeout unverified")
        self.identity = identity
        self._path = socket_path
        self._timeout = float(timeout_seconds)
        self._gate = Lock()
        self._closed = False
        self._active: asyncio.Task[object] | None = None
        self._completed: Future[None] | None = None
        self._closing: dict[CloseScope, Future[None]] = {}

    async def _exchange(self, request: EngineRequest, *, closing: bool = False) -> EngineReply:
        # A new transport owns one connection and reuses every existing UID,
        # inode, SO_PEERCRED, bounded length, EOF, deadline and close check.
        transport = UnixSyntheticBrowser(
            socket_path=self._path,
            timeout_seconds=min(self._timeout, 6.0) if closing else self._timeout,
        )
        raw = await transport._exchange(ENGINE_SESSION, None, private_payload=request.to_payload())
        reply = EngineReply.from_payload(raw)
        if (
            reply.identity != request.identity
            or reply.command != request.command
            or reply.close_scope != request.close_scope
        ):
            raise SyntheticIPCError("engine_correlation_unverified")
        if isinstance(reply.result, BocaAuthReply) and (
            request.auth is None or reply.result.nonce != request.auth.nonce
        ):
            raise SyntheticIPCError("engine_correlation_unverified")
        if reply.status not in {"OK", "CLOSED"}:
            reason = {
                "BUSY": "worker_busy",
                "NO_GO": "worker_no_go",
                "TEARDOWN_UNVERIFIED": "engine_teardown_unverified",
            }[reply.status]
            raise SyntheticIPCError(reason)
        return reply

    async def _invoke(self, request: EngineRequest) -> EngineReply:
        active = asyncio.current_task()
        if active is None:
            raise SyntheticIPCError("client_loop_unavailable")
        with self._gate:
            if self._closed:
                raise SyntheticIPCError("client_closed")
            if self._active is not None:
                raise SyntheticIPCError("client_busy")
            self._active = active
            completed: Future[None] = Future()
            self._completed = completed
        deadline = monotonic() + self._timeout
        try:
            reply = await self._exchange(request)
            # No await between acceptance and this per-session STOP fence.
            with self._gate:
                if self._closed or active.cancelling() or monotonic() >= deadline:
                    raise SyntheticIPCError("client_closed_or_expired")
                return reply
        finally:
            with self._gate:
                if self._active is active:
                    self._active = None
                completed.set_result(None)

    async def observe_queue(self) -> QueuePageObservation:
        reply = await self._invoke(EngineRequest(self.identity, "observe"))
        return cast(QueuePageObservation, reply.result)

    async def prepare_boca_login(self, operation: str) -> BocaAuthReadiness:
        if operation != self.identity.activation_id:
            raise SyntheticIPCError("engine_auth_correlation_unverified")
        reply = await self._invoke(EngineRequest(self.identity, "prepare_login"))
        return cast(BocaAuthReadiness, reply.result)

    async def login_boca(self, request: BocaAuthRequest) -> BocaAuthReply:
        reply = await self._invoke(EngineRequest(self.identity, "login", auth=request))
        return cast(BocaAuthReply, reply.result)

    async def inspect(self) -> SessionInspection:
        reply = await self._invoke(EngineRequest(self.identity, "inspect"))
        return cast(SessionInspection, reply.result)

    async def _close(self, scope: CloseScope) -> None:
        with self._gate:
            self._closed = True
            # A later STOP may retry an unacknowledged close on this permanently
            # fenced identity. Pending closes are shared across loops; a
            # successful acknowledgement stays cached. Never downgrade an
            # activation close to a session close when retrying it.
            if "activation" in self._closing:
                scope = "activation"
            previous = self._closing.get(scope)
            if (
                previous is not None
                and previous.done()
                and (previous.cancelled() or previous.exception() is not None)
            ):
                previous = None
            if previous is None:
                finished: Future[None] = Future()
                self._closing[scope] = finished
            else:
                finished = previous
            active, completed = self._active, self._completed
        if previous is not None:
            # A future can be safely awaited from either controller event loop.
            await asyncio.shield(asyncio.wrap_future(previous))
            return
        if active is not None and active is not asyncio.current_task() and not active.done():
            active.get_loop().call_soon_threadsafe(active.cancel)
        try:
            reply = await self._exchange(
                EngineRequest(self.identity, "close", close_scope=scope), closing=True
            )
            if reply.status != "CLOSED":
                raise SyntheticIPCError("engine_close_unverified")
            if completed is not None and not completed.done():
                done, pending = await asyncio.wait({asyncio.wrap_future(completed)}, timeout=1.0)
                if pending:
                    raise SyntheticIPCError("client_teardown_unverified")
                for result in done:
                    result.result()
            finished.set_result(None)
        except BaseException as exc:
            finished.set_exception(exc)
            raise

    async def close(self) -> None:
        await self._close("session")

    async def close_activation(self) -> None:
        await self._close("activation")


def make_engine_session(
    identity: EngineIdentity,
    *,
    socket_path: Path = SOCKET_PATH,
    timeout_seconds: float = 25.0,
) -> UnixEngineSession:
    return UnixEngineSession(identity, socket_path=socket_path, timeout_seconds=timeout_seconds)
