"""Two owner jobs on one receipt-bound worker, with independent cancellation.

The durable store authorizes work; this coordinator only schedules its scopes.
It never starts Docker, manufactures provider results or requests a ticket.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import isfinite
from threading import Event, Lock, RLock, Thread
from time import monotonic
from typing import Protocol, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from boca_socios.browser.boca_auth_protocol import BocaAuthReadiness, BocaAuthReply, BocaAuthRequest
from boca_socios.browser.engine_client import UnixEngineSession
from boca_socios.browser.engine_protocol import (
    BrowserKind,
    EngineIdentity,
    EngineName,
    SessionInspection,
)
from boca_socios.browser.queue_page_observation import QueuePageObservation
from boca_socios.panel.engine_intents import EngineActivation, EngineDecision, EngineIntentStore
from boca_socios.panel.lifecycle_intents import LifecycleConflict
from boca_socios.queue.private_pass_monitor import PrivateAutomaticObservationMonitor
from boca_socios.security.member_auth_contract import (
    BocaAuthObservation,
    CredentialReadAuthority,
    PrivateBocaAuthMonitor,
)

ENGINES: tuple[EngineName, ...] = ("queues_tokens", "browsers_members")
BROWSERS: tuple[BrowserKind, ...] = ("chromium", "firefox", "webkit")
_STOP_OPENING = {"NO_EVENT_OBSERVED", "QUEUE_INACTIVE", "CHALLENGE", "CHECK_FAILED", "UNKNOWN"}


class EngineSessionPort(Protocol):
    async def observe_queue(self) -> QueuePageObservation: ...

    async def prepare_boca_login(self, operation: str) -> BocaAuthReadiness: ...

    async def login_boca(self, request: BocaAuthRequest) -> BocaAuthReply: ...

    async def inspect(self) -> SessionInspection: ...

    async def close(self) -> None: ...

    async def close_activation(self) -> None: ...


class Authenticate(Protocol):
    def __call__(
        self,
        worker: EngineSessionPort,
        member_id: str,
        readiness: BocaAuthReadiness,
        *,
        credential_read_authority: CredentialReadAuthority,
        exchange_authority: Callable[[], bool],
    ) -> Awaitable[BocaAuthObservation]: ...


@dataclass(slots=True, repr=False)
class _Session:
    identity: EngineIdentity
    client: EngineSessionPort
    state: str = "OPENING"
    phase: str = "OPENING"
    created: bool = False
    observed_at: datetime | None = None
    observation: QueuePageObservation | None = None
    inspection: SessionInspection | None = None
    auth: BocaAuthObservation | None = None
    closed: bool = False
    failed: bool = False


@dataclass(slots=True)
class _Activation:
    record: EngineActivation
    cancelled: Event = field(default_factory=Event)
    sessions: dict[str, _Session] = field(default_factory=dict, repr=False)
    future: Future[None] | None = field(default=None, repr=False)
    task: asyncio.Task[None] | None = field(default=None, repr=False)
    children: set[asyncio.Task[None]] = field(default_factory=set, repr=False)
    closing: bool = False
    scope_closed: bool = False
    stop_opening: bool = False
    phase: str = "WAITING_FOR_WORKER"


@dataclass(frozen=True, slots=True, repr=False)
class PrivateSessionDetails:
    identity: EngineIdentity
    observation: QueuePageObservation | None
    inspection: SessionInspection | None
    auth: BocaAuthObservation | None
    state: str
    phase: str


def _display_url(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password:
            return ""
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except ValueError:
        return ""


def _audit_time(value: str) -> str:
    # SQLite CURRENT_TIMESTAMP is UTC, whereas the private UI requires an
    # explicit zone to avoid the tablet interpreting it as local time twice.
    stamp = datetime.fromisoformat(value)
    return (stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp).isoformat()


class EngineSessionCoordinator:
    """A process-local scheduler backed by per-engine durable authority.

    Construction reconciles history but opens no worker connection. A physical
    CLAIMED callback authorizes a boot-local epoch; only its APPLIED receipt
    permits session work. Each scope is fenced again before publication.
    """

    def __init__(
        self,
        *,
        store: EngineIntentStore,
        wake: Callable[[str], None],
        session_factory: Callable[[EngineIdentity], EngineSessionPort] | None = None,
        authenticate: Authenticate | None = None,
        automatic_monitor: PrivateAutomaticObservationMonitor | None = None,
        auth_monitor: PrivateBocaAuthMonitor | None = None,
        poll_seconds: float = 5.0,
        open_seconds: float = 8.0,
        receipt_seconds: float = 30.0,
    ) -> None:
        for value, minimum, maximum in (
            (poll_seconds, 0.001, 30),
            (open_seconds, 0, 60),
            (receipt_seconds, 0.01, 60),
        ):
            if (
                type(value) not in {float, int}
                or not isfinite(value)
                or not minimum <= value <= maximum
            ):
                raise ValueError("bounded engine timing required")
        self.store = store
        self._wake = wake
        self._factory = session_factory or cast(
            Callable[[EngineIdentity], EngineSessionPort], UnixEngineSession
        )
        self._authenticate = authenticate
        self._automatic = automatic_monitor
        self._auth = auth_monitor
        self._poll = float(poll_seconds)
        self._opening = float(open_seconds)
        self._receipt = float(receipt_seconds)
        self._lock = RLock()
        self._control = Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: Thread | None = None
        self._runs: dict[str, _Activation] = {}
        self._physical_epochs: set[str] = set()
        self._closed = False
        self._shutting_down = False
        self._last_automatic: datetime | None = None
        self._opening_gate: asyncio.Lock | None = None
        self._next_open = 0.0
        self.store.recover_cold()

    def _event_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._closed:
                raise RuntimeError("engine coordinator closed")
            if self._loop is None:
                loop = asyncio.new_event_loop()
                ready = Event()

                def serve() -> None:
                    asyncio.set_event_loop(loop)
                    ready.set()
                    loop.run_forever()
                    loop.close()

                self._loop = loop
                self._thread = Thread(target=serve, name="boca-owner-engines", daemon=True)
                self._thread.start()
                if not ready.wait(2):
                    raise RuntimeError("engine loop unavailable")
            return self._loop

    def _wake_decision(self, decision: EngineDecision) -> None:
        intent = decision.physical_intent
        if intent is not None and intent.status == "REQUESTED":
            self._wake(intent.operation_id)

    def start(
        self,
        engine: str,
        operation_id: str,
        *,
        member_id: str | None = None,
        counts: Mapping[str, int],
    ) -> EngineActivation:
        with self._control:
            with self._lock:
                if self._closed or self._shutting_down:
                    raise RuntimeError("engine coordinator unavailable")
            self.store.recover_cold()
            decision = self.store.start(engine, operation_id, member_id=member_id, counts=counts)
            record = decision.activation
            with self._lock:
                if record.activation_id not in self._runs and record.state in {
                    "REQUESTED",
                    "STARTING",
                    "RUNNING",
                }:
                    for key, previous in tuple(self._runs.items()):
                        if (
                            previous.record.engine == engine
                            and previous.future is not None
                            and previous.future.done()
                        ):
                            del self._runs[key]
                    run = _Activation(record)
                    self._runs[record.activation_id] = run
                    loop = self._event_loop()
                    run.future = asyncio.run_coroutine_threadsafe(self._run_activation(run), loop)
        # The committed activation survives a lost wake; a replay re-delivers
        # the same physical UUID instead of creating a second worker request.
        self._wake_decision(decision)
        return record

    def physical_started(self, start_id: str) -> None:
        """Called inside the existing host CLAIM; schedule only, never await ACK."""
        with self._lock:
            if self._closed:
                raise RuntimeError("engine coordinator closed")
            self._physical_epochs.add(start_id)

    def stop(
        self, engine: str, operation_id: str, *, activation_id: str, generation: int
    ) -> EngineActivation:
        decision = self.store.stop(
            engine, operation_id, activation_id=activation_id, generation=generation
        )
        with self._lock:
            run = self._runs.get(decision.activation.activation_id)
            loop = self._loop
            if run is not None:
                run.cancelled.set()
                if loop is not None:
                    if (
                        run.future is not None
                        and run.future.done()
                        and not run.scope_closed
                        and not self._shutting_down
                    ):
                        run.future = asyncio.run_coroutine_threadsafe(self._retry_close(run), loop)
                    else:
                        loop.call_soon_threadsafe(self._cancel_run, run)
        self._wake_decision(decision)
        return decision.activation

    @staticmethod
    def _cancel_once(task: asyncio.Task[None]) -> None:
        if not task.done() and not task.cancelling():
            task.cancel()

    def _cancel_run(self, run: _Activation) -> None:
        if run.task is not None and not run.closing:
            self._cancel_once(run.task)

    def _publish(self, run: _Activation, publish: Callable[[], None]) -> bool:
        record = run.record
        return self.store.publish_if_current(
            record.engine,
            record.activation_id,
            record.generation,
            publish,
            member_id=record.member_id,
        )

    async def _await_physical(self, run: _Activation) -> bool:
        deadline = monotonic() + self._receipt
        while not run.cancelled.is_set() and monotonic() < deadline:
            with self._lock:
                authorized = run.record.physical_start_id in self._physical_epochs
            if authorized and self._publish(run, lambda: None):
                return True
            current = next(
                (state for state in self.store.snapshot() if state.engine == run.record.engine),
                None,
            )
            if (
                current is None
                or current.activation_id != run.record.activation_id
                or current.state in {"STOP_REQUESTED", "STOPPED", "FAILED", "UNCERTAIN"}
            ):
                return False
            await asyncio.sleep(0.05)
        return False

    async def _run_activation(self, run: _Activation) -> None:
        run.task = asyncio.current_task()
        tasks: list[asyncio.Task[None]] = []
        failed = False
        try:
            if not await self._await_physical(run):
                failed = not run.cancelled.is_set()
                run.phase = "WORKER_RECEIPT_UNVERIFIED" if failed else "STOPPING"
                return
            self.store.transition(
                run.record.engine, run.record.activation_id, run.record.generation, "STARTING"
            )
            run.phase = "OPENING"
            # Interleave browser types so an early unavailable type does not
            # conceal the others. The worker enforces the global physical cap.
            kinds = [
                kind
                for index in range(max(run.record.counts.values()))
                for kind in BROWSERS
                if index < run.record.counts[kind]
            ]
            for kind in kinds:
                if (
                    run.cancelled.is_set()
                    or run.stop_opening
                    or not self._publish(run, lambda: None)
                ):
                    break
                await self._admit_opening()
                if (
                    run.cancelled.is_set()
                    or run.stop_opening
                    or not self._publish(run, lambda: None)
                ):
                    break
                identity = EngineIdentity(
                    run.record.engine,
                    run.record.activation_id,
                    run.record.generation,
                    str(uuid4()),
                    kind,
                )
                item = _Session(identity, self._factory(identity))
                with self._lock:
                    run.sessions[identity.session_id] = item
                task = asyncio.create_task(self._run_session(run, item))
                tasks.append(task)
                run.children.add(task)
                await asyncio.sleep(0)
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                failed = any(isinstance(result, BaseException) for result in results) or any(
                    item.failed for item in run.sessions.values()
                )
        except asyncio.CancelledError:
            run.cancelled.set()
            run.phase = "STOPPING"
        except Exception:
            failed = True
            run.phase = "ENGINE_FAILED"
        finally:
            await self._finish_activation(run, failed=failed)

    async def _retry_close(self, run: _Activation) -> None:
        """An explicit repeated STOP retries only its retired worker scope."""
        run.task = asyncio.current_task()
        await self._finish_activation(run, failed=False)

    async def _finish_activation(self, run: _Activation, *, failed: bool) -> None:
        run.closing = True
        try:
            for task in run.children:
                self._cancel_once(task)
            close_scope: asyncio.Task[None] | None = None
            if run.sessions:
                first = next(iter(run.sessions.values()))
                close_scope = asyncio.create_task(first.client.close_activation())
                run.children.add(close_scope)
            else:
                run.scope_closed = True
            pending: set[asyncio.Task[None]] = set()
            if run.children:
                _done, pending = await asyncio.wait(run.children, timeout=7)
                if pending:
                    failed = True
                    for task in pending:
                        self._cancel_once(task)
                if close_scope is not None and close_scope.done() and not close_scope.cancelled():
                    try:
                        close_scope.result()
                    except Exception:
                        failed = True
                    else:
                        run.scope_closed = True
                        for item in run.sessions.values():
                            item.closed = True
                            item.state = "FAILED" if item.failed else "CLOSED"
            closed = (
                run.scope_closed
                and not pending
                and all(item.closed for item in run.sessions.values())
            )
            if failed:
                try:
                    self.store.transition(
                        run.record.engine, run.record.activation_id, run.record.generation, "FAILED"
                    )
                except LifecycleConflict:
                    pass
            try:
                decision = self.store.release(
                    run.record.engine,
                    run.record.activation_id,
                    run.record.generation,
                    closed=closed,
                )
                self._wake_decision(decision)
            except Exception:
                run.phase = "CLOSE_UNVERIFIED"
            if not closed:
                run.phase = "CLOSE_UNVERIFIED"
            elif run.phase in {"STOPPING", "OPENING", "OBSERVING", "CLOSE_UNVERIFIED"}:
                run.phase = "STOPPED"
        finally:
            run.closing = False

    async def _admit_opening(self) -> None:
        # Pace the aggregate, not fifty concurrent requests queued inside the
        # worker's existing observation deadline. Waiting never holds a DB lock.
        if self._opening_gate is None:
            self._opening_gate = asyncio.Lock()
        async with self._opening_gate:
            delay = self._next_open - monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_open = monotonic() + self._opening

    async def _run_session(self, run: _Activation, item: _Session) -> None:
        try:
            while not run.cancelled.is_set() and self._publish(run, lambda: None):
                ready = None
                if run.record.engine == "browsers_members" and item.auth is None:
                    ready = await item.client.prepare_boca_login(run.record.activation_id)
                    if ready.operation_id != run.record.activation_id:
                        raise ValueError("authentication activation mismatch")
                    observed = ready.observation
                else:
                    observed = await item.client.observe_queue()
                inspected = await item.client.inspect()

                def publish_observation(
                    observed: QueuePageObservation = observed,
                    inspected: SessionInspection = inspected,
                ) -> None:
                    with self._lock:
                        item.observation = observed
                        item.inspection = inspected
                        item.observed_at = observed.observed_at
                        item.created = (
                            item.created
                            or inspected.context_open
                            or observed.outcome != "CHECK_FAILED"
                        )
                        item.state = "ACTIVE" if inspected.context_open else "OBSERVED"
                        item.phase = observed.outcome
                        run.phase = observed.outcome
                        if item.auth is not None:
                            item.phase = "AUTH_TOKENS_OBSERVED_DOM_UNVERIFIED"
                        if (
                            run.record.engine == "queues_tokens"
                            and self._automatic is not None
                            and (
                                self._last_automatic is None
                                or observed.observed_at >= self._last_automatic
                            )
                        ):
                            self._automatic.observe_global(observed)
                            self._last_automatic = observed.observed_at

                if not self._publish(run, publish_observation):
                    return
                self.store.transition(
                    run.record.engine, run.record.activation_id, run.record.generation, "RUNNING"
                )
                if ready is not None and ready.ready:
                    if self._authenticate is None or run.record.member_id is None:
                        raise RuntimeError("member authentication unavailable")
                    if not self._publish(run, lambda: self._set_phase(item, "AUTHENTICATING")):
                        return
                    received = await self._authenticate(
                        item.client,
                        run.record.member_id,
                        ready,
                        credential_read_authority=lambda connection, member_id: (
                            self.store.credential_read_authorized(
                                connection,
                                run.record.engine,
                                run.record.activation_id,
                                run.record.generation,
                                member_id,
                            )
                        ),
                        exchange_authority=lambda: self._publish(run, lambda: None),
                    )

                    def publish_auth(received: BocaAuthObservation = received) -> None:
                        with self._lock:
                            item.auth = received
                            item.phase = "AUTH_TOKENS_OBSERVED_DOM_UNVERIFIED"
                            run.phase = item.phase
                            if self._auth is not None:
                                self._auth.observe(received)

                    if not self._publish(run, publish_auth):
                        return
                elif observed.outcome in _STOP_OPENING and item.auth is None:
                    item.failed = observed.outcome in {"CHECK_FAILED", "UNKNOWN", "CHALLENGE"}
                    run.stop_opening = True
                    return
                await asyncio.sleep(self._poll)
        except asyncio.CancelledError:
            item.phase = "STOPPING"
        except Exception:
            item.failed = True
            item.phase = "SESSION_FAILED"
            # Another browser type or engine may still work. A local transport
            # failure is never an assertion that the provider has no events.
        finally:
            try:
                await item.client.close()
            except Exception:
                item.state = "UNCERTAIN"
                item.phase = "CLOSE_UNVERIFIED"
            else:
                item.closed = True
                item.state = "FAILED" if item.failed else "CLOSED"

    def _set_phase(self, item: _Session, phase: str) -> None:
        with self._lock:
            item.phase = phase

    async def _drain(self) -> None:
        with self._control, self._lock:
            self._shutting_down = True
            runs = tuple(self._runs.values())
            self._physical_epochs.clear()
        deadline = monotonic() + 8
        futures: list[asyncio.Future[None]] = []
        try:
            for run in runs:
                run.cancelled.set()
                self._cancel_run(run)
                if run.future is not None:
                    futures.append(asyncio.wrap_future(run.future))
            if futures:
                _, pending = await asyncio.wait(futures, timeout=max(0, deadline - monotonic()))
                if pending:
                    raise RuntimeError("engine shutdown unverified")
            children = {task for run in runs for task in run.children}
            if children:
                _, pending_children = await asyncio.wait(
                    children, timeout=max(0, deadline - monotonic())
                )
                if pending_children:
                    raise RuntimeError("engine local session drain unverified")
            # This callback certifies local coroutine drain only. An uncertain
            # worker scope keeps its durable hold until the protected runner
            # stops the worker and publishes the physical STOP/APPLIED receipt.
        finally:
            with self._lock:
                self._shutting_down = False

    async def shutdown_activation(self) -> None:
        """Drain before the existing engine socket acknowledges physical STOP.

        This callback never waits for the host ACK or calls stop_engine itself.
        It can be called from BetaCommandHost's different event loop.
        """
        with self._lock:
            loop = self._loop
        if loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._drain(), loop)
            await asyncio.wait_for(asyncio.wrap_future(future), timeout=10)

    def snapshot(self) -> dict[str, object]:
        records = {record.engine: record for record in self.store.snapshot()}
        restartable = self.store.restartable_engines()
        engines: list[dict[str, object]] = []
        with self._lock:
            for engine in ENGINES:
                record = records.get(engine)
                run = self._runs.get(record.activation_id) if record is not None else None
                sessions = tuple(run.sessions.values()) if run is not None else ()
                rows = [self._session_metadata(item) for item in sessions]
                engines.append(
                    {
                        "engine": engine,
                        "state": record.state if record else "STOPPED",
                        "activation_id": record.activation_id if record else None,
                        "generation": record.generation if record else 0,
                        "can_start": engine in restartable,
                        "member_id": record.member_id if record else None,
                        "counts": dict(record.counts)
                        if record
                        else dict(zip(BROWSERS, (15, 5, 5), strict=True)),
                        "requested_contexts": record.requested_contexts if record else 0,
                        "created": sum(item.created for item in sessions),
                        "active": sum(
                            item.inspection is not None
                            and item.inspection.context_open
                            and not item.closed
                            for item in sessions
                        ),
                        "closed": sum(item.closed for item in sessions),
                        "failed": sum(item.failed for item in sessions),
                        "phase": (
                            "PHYSICAL_STOP_CONFIRMED_PENDING_RECONCILIATION"
                            if record and not record.released and engine in restartable
                            else run.phase
                            if run
                            else "COLD"
                        ),
                        "updated_at": _audit_time(record.updated_at) if record else None,
                        "sessions": rows,
                    }
                )
        return {
            "version": 1,
            "context_limit": 50,
            "legacy_recovery_state": self.store.legacy_recovery_state(),
            "observed_at": datetime.now(UTC).isoformat(),
            "engines": engines,
        }

    @staticmethod
    def _session_metadata(item: _Session) -> dict[str, object]:
        inspected, observed = item.inspection, item.observation
        return {
            "session_id": item.identity.session_id,
            "browser": item.identity.browser,
            "state": item.state,
            "phase": item.phase,
            "observed_at": item.observed_at.isoformat() if item.observed_at else None,
            "outcome": observed.outcome if observed else None,
            "event_state": observed.event_state if observed else None,
            "event_id": observed.event_id if observed else None,
            "reason": observed.reason if observed else None,
            "queue_state": observed.queue_state if observed else "UNKNOWN",
            "has_target_url": observed is not None and observed.target_url is not None,
            "has_auth": item.auth is not None,
            "display_url": _display_url(inspected.final_url if inspected else None),
            "final_url_observed_at": (
                inspected.observed_at.isoformat()
                if inspected and inspected.final_url and inspected.observed_at
                else None
            ),
            "configured_url": inspected.configured_url if inspected else None,
            "navigation_attempt": (
                inspected.navigation_attempt.to_value()
                if inspected and inspected.navigation_attempt
                else None
            ),
            "queue_id": inspected.queue_id if inspected else None,
            "position": inspected.queue_number if inspected else None,
            "ahead": inspected.users_ahead if inspected else None,
            "queue_size": inspected.users_in_queue if inspected else None,
            "expected_service_time": inspected.expected_service_time if inspected else None,
            "countdown": None,
        }

    def private_details(
        self, session_id: str, *, owner_authenticated: bool
    ) -> PrivateSessionDetails | None:
        if owner_authenticated is not True:
            raise PermissionError("authenticated owner required")
        with self._lock:
            for run in self._runs.values():
                item = run.sessions.get(session_id)
                if item is not None:
                    return PrivateSessionDetails(
                        item.identity,
                        item.observation,
                        item.inspection,
                        item.auth,
                        item.state,
                        item.phase,
                    )
        return None

    def close(self) -> None:
        with self._control:
            with self._lock:
                if self._closed:
                    return
                self._closed = True
                loop, thread = self._loop, self._thread
        try:
            if loop is not None and loop.is_running():
                asyncio.run_coroutine_threadsafe(self._drain(), loop).result(timeout=10)
        finally:
            with self._lock:
                self._closed = True
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(loop.stop)
            if thread is not None:
                thread.join(timeout=2)
                if thread.is_alive():
                    raise RuntimeError("engine coordinator teardown unverified")
