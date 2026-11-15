"""Two logical engines, per-session gates and one bounded shared browser pool.

The registry is owned by the worker event loop. All identity, budget and STOP
fences are applied synchronously before awaiting browser work. Only this outer
adapter changes; the owner-controlled navigation modules remain opaque.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from math import isfinite
from time import monotonic
from typing import Any, Protocol

from boca_socios.browser import activity_events
from boca_socios.browser.automatic_observer import (
    AutomaticQueueObserver,
    BrowserFactory,
    EngineFactory,
    PlaywrightFactory,
    _Browser,
    _default_engine,
    _default_playwright,
)
from boca_socios.browser.boca_auth_protocol import BocaAuthReadiness, BocaAuthReply, BocaAuthRequest
from boca_socios.browser.engine_protocol import (
    MAX_CONTEXTS,
    BrowserKind,
    EngineIdentity,
    EngineName,
    EngineReply,
    EngineRequest,
    EngineResult,
    ReplyStatus,
    SessionInspection,
)
from boca_socios.browser.ipc_protocol import SyntheticIPCError
from boca_socios.browser.queue_page_observation import QueuePageObservation
from boca_socios.browser.worker_health import validate_worker_boundary


def _consume(task: asyncio.Task[object]) -> None:
    try:
        task.result()
    except (Exception, asyncio.CancelledError):
        return


def _seconds(value: float, maximum: float) -> float:
    if type(value) not in (int, float) or not isfinite(value) or not 0 < value <= maximum:
        raise ValueError("engine deadline unverified")
    return float(value)


class SessionObserver(Protocol):
    async def observe_queue(self) -> QueuePageObservation: ...
    async def prepare_boca_login(self, operation: str) -> BocaAuthReadiness: ...
    async def login_boca(self, request: BocaAuthRequest) -> BocaAuthReply: ...
    async def inspect(self) -> SessionInspection: ...
    async def close(self) -> None: ...


ObserverFactory = Callable[[EngineIdentity], SessionObserver]


class SharedBrowserPool:
    """At most one ordinary process per type; a loan owns no process lifetime."""

    def __init__(
        self,
        *,
        playwright_factory: PlaywrightFactory = _default_playwright,
        boundary_check: Callable[[], None] = validate_worker_boundary,
        opening_interval: float = 8.0,
        teardown_seconds: float = 4.0,
    ) -> None:
        if (
            type(opening_interval) not in (int, float)
            or not isfinite(opening_interval)
            or not 0 <= opening_interval <= 30
        ):
            raise ValueError("engine opening interval unverified")
        self._factory = playwright_factory
        self._check = boundary_check
        self._interval = float(opening_interval)
        self._teardown = _seconds(teardown_seconds, 5.0)
        self._manager: AbstractAsyncContextManager[object] | None = None
        self._browsers: dict[BrowserKind, _Browser] = {}
        self._unavailable: set[BrowserKind] = set()
        self._launch_gate = asyncio.Lock()
        self._pace_gate = asyncio.Lock()
        self.initialization_lock = asyncio.Lock()
        self._api: object | None = None
        self._starting: asyncio.Task[object] | None = None
        self._last_opening: float | None = None
        self._closed = False
        self._launching: asyncio.Task[_Browser] | None = None

    def browser_factory(self, kind: BrowserKind) -> BrowserFactory:
        if kind not in {"chromium", "firefox", "webkit"}:
            raise SyntheticIPCError("engine_browser_unverified")

        @asynccontextmanager
        async def loan() -> AsyncIterator[_Browser]:
            # Pace context admissions globally, including different browser types.
            # This gate never covers an established session's poll or STOP.
            async with self._pace_gate:
                if self._last_opening is not None:
                    remaining = self._last_opening + self._interval - monotonic()
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                if self._closed:
                    raise SyntheticIPCError("engine_pool_closed")
                self._last_opening = monotonic()
            async with self._launch_gate:
                if self._closed:
                    raise SyntheticIPCError("engine_pool_closed")
                if kind in self._unavailable:
                    raise SyntheticIPCError("engine_browser_unavailable")
                self._check()
                if self._api is None:
                    manager = self._factory()
                    self._manager = manager
                    starting: asyncio.Task[object] = asyncio.create_task(manager.__aenter__())
                    self._starting = starting

                    def remember_api(task: asyncio.Task[object]) -> None:
                        try:
                            self._api = task.result()
                        except (Exception, asyncio.CancelledError):
                            return

                    starting.add_done_callback(remember_api)
                    try:
                        self._api = await asyncio.shield(starting)
                    except BaseException:
                        # The driver may already exist remotely. Keep its entry
                        # task and manager until shutdown obtains the late handle
                        # or reports uncertainty; another loan cannot replace it.
                        self._closed = True
                        raise SyntheticIPCError("engine_launch_unverified") from None
                if self._closed:
                    raise SyntheticIPCError("engine_pool_closed")
                browser = self._browsers.get(kind)
                if browser is None:
                    browser_type = getattr(self._api, kind)
                    options: dict[str, object] = {"headless": True, "timeout": 12000}
                    if kind == "chromium":
                        options.update(
                            chromium_sandbox=True, args=["--disable-background-networking"]
                        )
                        activity_events.emit_chromium_event("launch_requested")
                    launching = asyncio.create_task(browser_type.launch(**options))
                    self._launching = launching

                    def remember_process(task: asyncio.Task[_Browser]) -> None:
                        # Ownership transfers even if cancellation arrives just
                        # before launch returns. Pool teardown then sees and
                        # closes that late process rather than losing its handle.
                        try:
                            self._browsers[kind] = task.result()
                        except (Exception, asyncio.CancelledError):
                            return
                        if kind == "chromium":
                            activity_events.emit_chromium_event("launched")

                    launching.add_done_callback(remember_process)
                    launching.add_done_callback(_consume)
                    try:
                        done, pending = await asyncio.wait({launching}, timeout=12.0)
                        if pending or self._closed:
                            raise SyntheticIPCError("engine_launch_unverified")
                        browser = launching.result()
                        self._browsers[kind] = browser
                    except BaseException as exc:
                        if (
                            launching.done()
                            and not launching.cancelled()
                            and not isinstance(exc, asyncio.CancelledError)
                            and not (
                                isinstance(exc, SyntheticIPCError)
                                and str(exc) == "engine_launch_unverified"
                            )
                        ):
                            # A completed failed launch (including missing
                            # binary/dependencies) is unavailable for this
                            # worker lifetime; do not repeatedly spawn it or
                            # discard the other already available browser types.
                            self._unavailable.add(kind)
                            raise SyntheticIPCError("engine_browser_unavailable") from None
                        # A pending browser launch cannot safely be reused. The
                        # owning registry reports uncertainty and retires worker.
                        self._closed = True
                        launching.cancel()
                        raise SyntheticIPCError("engine_launch_unverified") from None
                    finally:
                        if launching.done():
                            self._launching = None
            if self._closed:
                raise SyntheticIPCError("engine_pool_closed")
            yield browser
            # The observer closes its own context; returning the loan must never
            # close a process still used by the other functional engine.

        return loan

    async def close(self) -> None:
        self._closed = True
        deadline = monotonic() + self._teardown
        starting = self._starting
        if starting is not None and not starting.done():
            _, pending_start = await asyncio.wait({starting}, timeout=self._teardown)
            if pending_start:
                manager, self._manager = self._manager, None
                if manager is not None:
                    late_manager = manager

                    def close_late_manager(_task: asyncio.Task[object]) -> None:
                        closing = asyncio.create_task(late_manager.__aexit__(None, None, None))
                        closing.add_done_callback(_consume)

                    starting.add_done_callback(close_late_manager)
                raise SyntheticIPCError("engine_teardown_unverified")
        launching = self._launching
        if launching is not None and not launching.done():
            launching.cancel()
            _, pending_launch = await asyncio.wait({launching}, timeout=self._teardown)
            if pending_launch:
                launching.cancel()
                raise SyntheticIPCError("engine_teardown_unverified")
        closing_browsers: dict[asyncio.Task[object], BrowserKind] = {
            asyncio.create_task(browser.close()): kind for kind, browser in self._browsers.items()
        }
        tasks = set(closing_browsers)
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=max(0.0, deadline - monotonic()))
            for task in pending:
                task.cancel()
                task.add_done_callback(_consume)
            failed = bool(pending)
            for task in done:
                try:
                    task.result()
                except (Exception, asyncio.CancelledError):
                    failed = True
                else:
                    if closing_browsers[task] == "chromium":
                        activity_events.emit_chromium_event("browser_closed")
            if failed:
                raise SyntheticIPCError("engine_teardown_unverified")
        if self._manager is not None:
            manager, self._manager = self._manager, None
            closing = asyncio.create_task(manager.__aexit__(None, None, None))
            closing.add_done_callback(_consume)
            _, pending = await asyncio.wait({closing}, timeout=max(0.0, deadline - monotonic()))
            if pending:
                closing.cancel()
                raise SyntheticIPCError("engine_teardown_unverified")
            closing.result()
        self._browsers.clear()


@dataclass(slots=True)
class _Activation:
    activation_id: str
    generation: int
    closed: bool = False


@dataclass(slots=True)
class _Session:
    identity: EngineIdentity
    observer: SessionObserver | None = None
    active: asyncio.Task[EngineResult] | None = None
    closing: asyncio.Task[None] | None = None
    closed: bool = False
    released: bool = False
    uncertain: bool = False
    nonce: str | None = None
    nonce_deadline: float = 0.0
    auth_used: bool = False


class EngineSessionRegistry:
    """Lifetime-bounded tombstones stop delayed requests from reopening sessions."""

    def __init__(
        self,
        *,
        observer_factory: ObserverFactory,
        pool: SharedBrowserPool | None = None,
        operation_seconds: float = 20.0,
        teardown_seconds: float = 4.0,
    ) -> None:
        self._factory = observer_factory
        self._pool = pool
        self._operation = _seconds(operation_seconds, 20.0)
        self._teardown = _seconds(teardown_seconds, 5.0)
        self._activations: dict[EngineName, _Activation] = {}
        self._activation_owners: dict[str, EngineName] = {}
        self._sessions: dict[str, _Session] = {}
        self._closed = False
        self._poisoned = False

    @property
    def live_contexts(self) -> int:
        return sum(
            session.observer is not None and not session.released
            for session in self._sessions.values()
        )

    @property
    def poisoned(self) -> bool:
        return self._poisoned

    def _admit_activation(self, ident: EngineIdentity) -> ReplyStatus | None:
        owner = self._activation_owners.get(ident.activation_id)
        if owner is not None and owner != ident.engine:
            return "NO_GO"
        current = self._activations.get(ident.engine)
        if current is not None:
            if (current.activation_id, current.generation) == (
                ident.activation_id,
                ident.generation,
            ):
                return None
            if ident.generation <= current.generation or owner is not None:
                return "NO_GO"
            if not current.closed:
                return "BUSY"
        if len(self._activation_owners) >= 4096:
            return "BUSY"
        self._activation_owners[ident.activation_id] = ident.engine
        self._activations[ident.engine] = _Activation(ident.activation_id, ident.generation)
        return None

    @staticmethod
    def _reply(
        request: EngineRequest, status: ReplyStatus, result: EngineResult = None
    ) -> EngineReply:
        return EngineReply(request.identity, request.command, status, result, request.close_scope)

    def _fence(self, session: _Session) -> None:
        session.closed = True
        session.nonce = None
        if (
            session.active is not None
            and not session.active.done()
            and not session.active.cancelling()
        ):
            session.active.cancel()

    async def _finish_close(self, session: _Session) -> None:
        deadline = monotonic() + self._teardown
        tasks: set[asyncio.Task[object]] = set()
        active = session.active
        if active is not None and not active.done():
            tasks.add(active)
        if session.observer is not None:
            closing = asyncio.create_task(session.observer.close())
            closing.add_done_callback(_consume)
            tasks.add(closing)
        failed = session.uncertain
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=max(0.0, deadline - monotonic()))
            failed = failed or bool(pending)
            for task in pending:
                task.cancel()
            for task in done:
                try:
                    task.result()
                except asyncio.CancelledError:
                    # The active operation is expected to be cancelled; a
                    # cancelled cleanup, in contrast, does not prove release.
                    if task is not active:
                        failed = True
                except Exception:
                    if task is not active:
                        failed = True
        if failed or session.uncertain:
            session.uncertain = True
            self._poisoned = True
            raise SyntheticIPCError("engine_teardown_unverified")
        session.released = True

    async def _close_sessions(self, entries: list[_Session]) -> bool:
        # Fence ALL targeted identities before the first cancellation/close await.
        for session in entries:
            self._fence(session)
        tasks = []
        for session in entries:
            if session.closing is None:
                session.closing = asyncio.create_task(self._finish_close(session))
                session.closing.add_done_callback(_consume)
            tasks.append(session.closing)
        if tasks:
            results = await asyncio.gather(
                *(asyncio.shield(task) for task in tasks), return_exceptions=True
            )
            return not any(isinstance(result, BaseException) for result in results)
        return True

    async def execute(self, request: EngineRequest) -> EngineReply:
        ident = request.identity
        if self._closed or self._poisoned:
            return self._reply(request, "TEARDOWN_UNVERIFIED" if self._poisoned else "NO_GO")
        session = self._sessions.get(ident.session_id)
        if session is not None and session.identity != ident:
            return self._reply(request, "NO_GO")
        rejected = self._admit_activation(ident)
        if rejected is not None:
            return self._reply(request, rejected)
        activation = self._activations[ident.engine]
        if request.command == "close":
            if request.close_scope == "activation":
                activation.closed = True
                entries = [
                    entry
                    for entry in self._sessions.values()
                    if entry.identity.engine == ident.engine
                    and entry.identity.activation_id == ident.activation_id
                ]
            else:
                if session is None:
                    if len(self._sessions) >= 4096:
                        return self._reply(request, "BUSY")
                    session = _Session(ident)
                    self._sessions[ident.session_id] = session
                entries = [session]
            good = await self._close_sessions(entries)
            return self._reply(request, "CLOSED" if good else "TEARDOWN_UNVERIFIED")
        if activation.closed or (session is not None and session.closed):
            return self._reply(request, "NO_GO")
        if session is None:
            if request.command in {"login", "inspect"}:
                return self._reply(request, "NO_GO")
            if self.live_contexts >= MAX_CONTEXTS or len(self._sessions) >= 4096:
                return self._reply(request, "BUSY")
            session = _Session(ident)
            self._sessions[ident.session_id] = session
            try:
                session.observer = self._factory(ident)
            except Exception:
                session.closed = True
                session.released = True
                return self._reply(request, "NO_GO")
        if session.active is not None:
            return self._reply(request, "BUSY")
        observer = session.observer
        if observer is None:
            return self._reply(request, "NO_GO")
        job: Coroutine[Any, Any, EngineResult]
        if request.command == "login":
            if (
                session.auth_used
                or request.auth is None
                or session.nonce is None
                or request.auth.nonce != session.nonce
                or monotonic() >= session.nonce_deadline
            ):
                return self._reply(request, "NO_GO")
            session.auth_used = True
            session.nonce = None
            job = observer.login_boca(request.auth)
        elif request.command == "prepare_login":
            if session.auth_used:
                return self._reply(request, "NO_GO")
            job = observer.prepare_boca_login(ident.activation_id)
        elif request.command == "inspect":
            job = observer.inspect()
        else:
            job = observer.observe_queue()
        active: asyncio.Task[EngineResult] = asyncio.create_task(job)
        session.active = active
        active.add_done_callback(_consume)
        deadline = monotonic() + self._operation
        try:
            _, pending = await asyncio.wait({active}, timeout=self._operation)
            if pending:
                await self._close_sessions([session])
                return self._reply(request, "TEARDOWN_UNVERIFIED" if session.uncertain else "NO_GO")
            result = active.result()
            if (
                self._closed
                or self._poisoned
                or session.closed
                or activation.closed
                or active.cancelling()
                or monotonic() >= deadline
            ):
                return self._reply(request, "NO_GO")
            response = self._reply(request, "OK", result)
            if isinstance(result, BocaAuthReadiness):
                session.nonce = result.nonce
                session.nonce_deadline = monotonic() + result.remaining_seconds
            return response
        except asyncio.CancelledError:
            await self._close_sessions([session])
            return self._reply(request, "NO_GO")
        except Exception as exc:
            if isinstance(exc, SyntheticIPCError) and str(exc) in {
                "automatic_observer_teardown_unverified",
                "boca_login_teardown_unverified",
                "engine_launch_unverified",
                "engine_pool_closed",
            }:
                self._poisoned = True
                session.uncertain = True
            await self._close_sessions([session])
            return self._reply(request, "TEARDOWN_UNVERIFIED" if self._poisoned else "NO_GO")
        finally:
            if session.active is active:
                session.active = None

    async def close(self) -> None:
        self._closed = True
        for activation in self._activations.values():
            activation.closed = True
        good = await self._close_sessions(list(self._sessions.values()))
        if self._pool is not None:
            try:
                await self._pool.close()
            except (Exception, asyncio.CancelledError):
                good = False
        if not good or self._poisoned:
            raise SyntheticIPCError("engine_teardown_unverified")


def automatic_engine_registry(
    site_url: str,
    *,
    pool: SharedBrowserPool | None = None,
    engine_factory: EngineFactory = _default_engine,
    boundary_check: Callable[[], None] = validate_worker_boundary,
) -> EngineSessionRegistry:
    """Construction is inert. Each V2 observer explicitly retains its own page."""
    shared = pool if pool is not None else SharedBrowserPool(boundary_check=boundary_check)

    def observer(ident: EngineIdentity) -> SessionObserver:
        return AutomaticQueueObserver(
            site_url,
            browsers=shared.browser_factory(ident.browser),
            engine_factory=engine_factory,
            boundary_check=boundary_check,
            initialization_lock=shared.initialization_lock,
            retain_until_closed=True,
            retain_after_auth=ident.engine == "browsers_members",
            chromium_activity=ident.browser == "chromium",
        )

    return EngineSessionRegistry(observer_factory=observer, pool=shared)
