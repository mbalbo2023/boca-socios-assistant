"""Two actual durable activations share infrastructure, never cancellation."""

import asyncio
import importlib
from datetime import UTC, datetime
from functools import partial
from threading import Event, Lock, Thread
from types import SimpleNamespace
from uuid import uuid4

import pytest

from boca_socios.browser.boca_auth_protocol import BocaAuthReadiness
from boca_socios.browser.engine_protocol import NavigationAttempt, SessionInspection
from boca_socios.browser.queue_page_observation import parse_queue_page_observation
from boca_socios.integration.command_store import CommandStore
from boca_socios.panel.lifecycle_intents import LifecycleIntentStore
from boca_socios.reservation_guard import ReservationAttemptGuard
from test_bot_work_session import confirm_start
from test_member_auth_contract import _enrolled


def prepared_store(tmp_path):
    from boca_socios.panel.engine_intents import EngineIntentStore

    db, vault, member = _enrolled(tmp_path)
    CommandStore(db).migrate()
    guard = ReservationAttemptGuard(db)
    guard.migrate()
    guard.migrate_simulation()
    return db, vault, member, EngineIntentStore(db, boot_id=str(uuid4()))


class WaitingSession:
    """Only the external worker is replaced; lifecycle/storage stay real."""

    def __init__(self, identity):
        self.identity = identity
        self.observed = Event()
        self.again = Event()
        self.closed = Event()
        self.calls = 0

    async def observe_queue(self):
        assert not self.closed.is_set()
        self.calls += 1
        self.observed.set()
        if self.calls > 1:
            self.again.set()
        return parse_queue_page_observation(
            final_url="https://offline.example.invalid/",
            queue_model=None,
            markers=frozenset({"prequeue"}),
            observed_at=datetime.now(UTC),
        )

    async def prepare_boca_login(self, operation):
        assert operation == self.identity.activation_id
        return BocaAuthReadiness(operation, await self.observe_queue(), None, 0)

    async def inspect(self):
        return SimpleNamespace(
            final_url="https://offline.example.invalid/?private=never-in-metadata",
            queue_id="queue-fixture",
            queue_number=31,
            users_ahead=30,
            users_in_queue=100,
            expected_service_time=None,
            observed_at=datetime.now(UTC),
            context_open=not self.closed.is_set(),
            auth_response_received=False,
            dom_authentication="UNVERIFIED",
            configured_url=None,
            navigation_attempt=None,
        )

    async def close(self):
        self.closed.set()

    async def close_activation(self):
        self.closed.set()


def coordinator(tmp_path, *, session_type=WaitingSession):
    api = importlib.import_module("boca_socios.integration.engine_sessions")
    db, vault, member, store = prepared_store(tmp_path)
    sessions, wakes = {}, []
    opened = {engine: Event() for engine in ("queues_tokens", "browsers_members")}
    guard = Lock()

    def factory(identity):
        worker = session_type(identity)
        with guard:
            sessions[identity.engine] = worker
            opened[identity.engine].set()
        return worker

    service = api.EngineSessionCoordinator(
        store=store,
        wake=wakes.append,
        session_factory=factory,
        poll_seconds=0.02,
        open_seconds=0,
        receipt_seconds=2,
    )
    return service, db, store, member, sessions, wakes, opened


@pytest.mark.parametrize(
    "page, expected",
    [
        (
            {"queue_model": {"eventId": "provider-match-301"}, "markers": frozenset({"prequeue"})},
            ("EVENT_ANNOUNCED", "provider-match-301", "OBSERVED_PREQUEUE"),
        ),
        (
            {"queue_model": {"eventId": "provider-match-301"}, "markers": frozenset({"queueid"})},
            ("EVENT_VERIFIED", "provider-match-301", "OBSERVED_QUEUE"),
        ),
        (
            {"queue_model": {"eventId": "provider-match-301"}},
            ("EVENT_VERIFIED", "provider-match-301", "EVENT_ID_OBSERVED"),
        ),
        (
            {"visible_text": "No hay eventos disponibles"},
            ("NO_EVENT_CONFIRMED", None, "EXPLICIT_NO_EVENTS"),
        ),
        ({"check_failed": True}, ("UNRECOGNIZED", None, "CHECK_FAILED")),
        ({"http_status": 503}, ("UNRECOGNIZED", None, "HTTP_FAILURE")),
        ({"markers": frozenset({"challenge"})}, ("UNRECOGNIZED", None, "VISIBLE_CHALLENGE")),
        ({}, ("UNRECOGNIZED", None, "NO_RECOGNIZED_EVIDENCE")),
    ],
    ids=["prequeue", "queue", "event-only", "absence", "failure", "http", "challenge", "unknown"],
)
def test_metadata_projects_observed_event_without_local_identity_inference(
    tmp_path, page, expected
):
    # Dropping or inferring the provider ID, or flattening error into absence,
    # must fail at the real coordinator's public metadata boundary.
    class ObservedPageSession(WaitingSession):
        async def observe_queue(self):
            await super().observe_queue()
            return parse_queue_page_observation(
                **{
                    "final_url": "https://offline.example.invalid/",
                    "queue_model": None,
                    "markers": frozenset(),
                    "observed_at": datetime(2026, 11, 15, 12, tzinfo=UTC),
                    **page,
                }
            )

    service, db, _store, member, sessions, _wakes, opened = coordinator(
        tmp_path, session_type=ObservedPageSession
    )
    run = service.start(
        "browsers_members",
        str(uuid4()),
        member_id=member,
        counts={"chromium": 1, "firefox": 0, "webkit": 0},
    )
    service.physical_started(run.physical_start_id)
    confirm_start(db, run.physical_start_id)
    try:
        assert opened[run.engine].wait(3)
        worker = sessions[run.engine]
        # A second observation starts after publication; terminal observations
        # instead close only after the same publication boundary.
        signal = (
            worker.again
            if expected[2] in {"OBSERVED_PREQUEUE", "OBSERVED_QUEUE"}
            else worker.closed
        )
        assert signal.wait(3)
        engine = next(row for row in service.snapshot()["engines"] if row["engine"] == run.engine)
        row = engine["sessions"][0]
        assert engine["member_id"] == member
        assert (row["event_state"], row["event_id"], row["reason"]) == expected
        assert row["event_id"] != member
        assert row["observed_at"] == "2026-11-15T12:00:00+00:00"
        assert "never-in-metadata" not in repr(row)
    finally:
        service.close()


@pytest.mark.parametrize(
    "evidence", ["failed", "missing_attempt", "missing_configuration", "no_final"]
)
def test_metadata_keeps_attempt_distinct_from_last_final_sample(tmp_path, evidence):
    # Using the latest observation's clock for an older final URL, or filling
    # a missing attempt/configuration from another URL, must fail here.
    class InspectedPageSession(WaitingSession):
        async def observe_queue(self):
            await super().observe_queue()
            return parse_queue_page_observation(
                final_url="https://offline.example.invalid/prior-final",
                queue_model=None,
                markers=frozenset({"prequeue"}),
                observed_at=datetime(2026, 11, 15, 12, 2, tzinfo=UTC),
            )

        async def inspect(self):
            sample = SessionInspection(
                final_url=(
                    None
                    if evidence == "no_final"
                    else "https://offline.example.invalid/prior-final?private=hidden#private-fragment"
                ),
                observed_at=datetime(2026, 11, 15, 12, tzinfo=UTC),
                context_open=True,
                configured_url=(
                    None
                    if evidence == "missing_configuration"
                    else "https://offline.example.invalid/configured"
                ),
                navigation_attempt=(
                    NavigationAttempt(
                        sequence=2,
                        purpose="QUEUE_BRIDGE",
                        display_url="https://queue.example.invalid/attempted",
                        started_at=datetime(2026, 11, 15, 12, 1, tzinfo=UTC),
                        result="FAILED",
                    )
                    if evidence in {"failed", "no_final"}
                    else None
                ),
            )
            return SessionInspection.from_payload(sample.to_payload())

    service, db, _store, _member, sessions, _wakes, opened = coordinator(
        tmp_path, session_type=InspectedPageSession
    )
    run = service.start(
        "queues_tokens", str(uuid4()), counts={"chromium": 1, "firefox": 0, "webkit": 0}
    )
    service.physical_started(run.physical_start_id)
    confirm_start(db, run.physical_start_id)
    try:
        assert opened[run.engine].wait(3) and sessions[run.engine].again.wait(3)
        engine = next(row for row in service.snapshot()["engines"] if row["engine"] == run.engine)
        row = engine["sessions"][0]
        assert row["observed_at"] == "2026-11-15T12:02:00+00:00"
        assert row["display_url"] == (
            "" if evidence == "no_final" else "https://offline.example.invalid/prior-final"
        )
        assert row["final_url_observed_at"] == (
            None if evidence == "no_final" else "2026-11-15T12:00:00+00:00"
        )
        assert row["configured_url"] == (
            None
            if evidence == "missing_configuration"
            else "https://offline.example.invalid/configured"
        )
        assert row["navigation_attempt"] == (
            {
                "sequence": 2,
                "purpose": "QUEUE_BRIDGE",
                "display_url": "https://queue.example.invalid/attempted",
                "started_at": "2026-11-15T12:01:00+00:00",
                "result": "FAILED",
                "http_status": None,
            }
            if evidence in {"failed", "no_final"}
            else None
        )
        assert "private=hidden" not in repr(row)
        assert "private-fragment" not in repr(row)
    finally:
        service.close()


def test_target_failure_without_inspection_keeps_metadata_unreceived(tmp_path):
    class FailedTargetSession(WaitingSession):
        inspect_calls = 0

        async def prepare_boca_login(self, operation):
            raise OSError("offline private failure text")

        async def inspect(self):
            self.inspect_calls += 1
            return await super().inspect()

    service, db, _store, member, sessions, _wakes, opened = coordinator(
        tmp_path, session_type=FailedTargetSession
    )
    run = service.start(
        "browsers_members",
        str(uuid4()),
        member_id=member,
        counts={"chromium": 1, "firefox": 0, "webkit": 0},
    )
    service.physical_started(run.physical_start_id)
    confirm_start(db, run.physical_start_id)
    try:
        assert opened[run.engine].wait(3)
        service._runs[run.activation_id].future.result(timeout=3)
        engine = next(row for row in service.snapshot()["engines"] if row["engine"] == run.engine)
        row = engine["sessions"][0]
        assert row["state"] == "FAILED" and row["phase"] == "SESSION_FAILED"
        assert sessions[run.engine].inspect_calls == 0
        for key in (
            "event_state",
            "event_id",
            "reason",
            "configured_url",
            "navigation_attempt",
            "final_url_observed_at",
            "observed_at",
        ):
            assert row[key] is None
        assert row["display_url"] == ""
        assert "offline private failure text" not in repr(row)
    finally:
        service.close()


@pytest.mark.parametrize("first", ["queues_tokens", "browsers_members"])
def test_stop_one_engine_keeps_other_activation_and_page_progressing(tmp_path, first):
    service, db, store, member, sessions, wakes, opened = coordinator(tmp_path)
    second = "browsers_members" if first == "queues_tokens" else "queues_tokens"
    counts = {"chromium": 1, "firefox": 0, "webkit": 0}
    try:
        first_run = service.start(
            first,
            str(uuid4()),
            member_id=member if first == "browsers_members" else None,
            counts=counts,
        )
        assert sessions == {}  # No browser work before the physical receipt.
        service.physical_started(first_run.physical_start_id)
        confirm_start(db, first_run.physical_start_id)
        second_run = service.start(
            second,
            str(uuid4()),
            member_id=member if second == "browsers_members" else None,
            counts=counts,
        )
        assert opened[first].wait(3)
        assert opened[second].wait(3)
        assert sessions[first].observed.wait(2)
        assert sessions[second].observed.wait(2)
        retained = sessions[second]
        retained.again.clear()
        service.stop(
            first,
            str(uuid4()),
            activation_id=first_run.activation_id,
            generation=first_run.generation,
        )
        assert sessions[first].closed.wait(2)
        assert retained.again.wait(2)
        assert not retained.closed.is_set()
        assert sessions[second] is retained
        assert LifecycleIntentStore(db).current().operation_id == first_run.physical_start_id
        current = {item.engine: item for item in store.snapshot()}
        assert current[second].activation_id == second_run.activation_id
        assert len(wakes) == 1  # Joining/stopping one job never wakes a second physical START.
        snapshot = service.snapshot()
        assert "never-in-metadata" not in repr(snapshot)
        assert "?private=" not in repr(snapshot)
    finally:
        service.close()


def test_cold_coordinator_does_not_adopt_old_applied_or_reopen_pages(tmp_path):
    service, db, store, _member, sessions, _wakes, opened = coordinator(tmp_path)
    first = service.start(
        "queues_tokens", str(uuid4()), counts={"chromium": 1, "firefox": 0, "webkit": 0}
    )
    service.physical_started(first.physical_start_id)
    confirm_start(db, first.physical_start_id)
    assert opened["queues_tokens"].wait(3)
    assert sessions["queues_tokens"].observed.wait(2)
    service.close()
    # A fresh coordinator never treats an old physical START as permission.
    from boca_socios.integration.engine_sessions import EngineSessionCoordinator
    from boca_socios.panel.engine_intents import EngineIntentStore

    opened = []
    fresh = EngineSessionCoordinator(
        store=EngineIntentStore(db, boot_id=str(uuid4())),
        wake=lambda _: None,
        session_factory=lambda identity: opened.append(identity),
    )
    try:
        assert opened == []
        assert all(row["active"] == 0 for row in fresh.snapshot()["engines"])
    finally:
        fresh.close()


def test_physical_shutdown_callback_drains_jobs_without_waiting_for_host_ack(tmp_path):
    service, db, store, _member, sessions, wakes, opened = coordinator(tmp_path)
    run = service.start(
        "queues_tokens", str(uuid4()), counts={"chromium": 1, "firefox": 0, "webkit": 0}
    )
    service.physical_started(run.physical_start_id)
    confirm_start(db, run.physical_start_id)
    assert opened["queues_tokens"].wait(3)
    assert sessions["queues_tokens"].observed.wait(2)
    physical_stop = LifecycleIntentStore(db).request("bot", "stop", str(uuid4()), on_demand=True)
    try:
        asyncio.run(service.shutdown_activation())
        assert sessions["queues_tokens"].closed.is_set()
        assert LifecycleIntentStore(db).current().operation_id == physical_stop.operation_id
        assert len(wakes) == 1
    finally:
        service.close()


def test_lost_activation_close_ack_retains_hold_and_retry_preserves_other_engine(tmp_path):
    class InterruptedActivationClose(WaitingSession):
        failures = 1

        async def close_activation(self):
            if self.identity.engine == "queues_tokens" and self.failures:
                self.failures -= 1
                raise OSError("offline lost activation acknowledgement")
            await super().close_activation()

    service, db, store, member, sessions, _wakes, opened = coordinator(
        tmp_path, session_type=InterruptedActivationClose
    )
    counts = {"chromium": 1, "firefox": 0, "webkit": 0}
    first = service.start("queues_tokens", str(uuid4()), counts=counts)
    service.physical_started(first.physical_start_id)
    confirm_start(db, first.physical_start_id)
    second = service.start("browsers_members", str(uuid4()), member_id=member, counts=counts)
    try:
        assert opened[first.engine].wait(3) and opened[second.engine].wait(3)
        assert sessions[first.engine].observed.wait(2)
        assert sessions[second.engine].observed.wait(2)
        service.stop(
            first.engine,
            str(uuid4()),
            activation_id=first.activation_id,
            generation=first.generation,
        )
        service._runs[first.activation_id].future.result(timeout=3)
        state = next(item for item in store.snapshot() if item.engine == first.engine)
        assert state.state == "UNCERTAIN" and not state.released
        assert not next(
            row for row in service.snapshot()["engines"] if row["engine"] == first.engine
        )["can_start"]
        retained = sessions[second.engine]
        retained.again.clear()
        service.stop(
            first.engine,
            str(uuid4()),
            activation_id=first.activation_id,
            generation=first.generation,
        )
        service._runs[first.activation_id].future.result(timeout=3)
        state = next(item for item in store.snapshot() if item.engine == first.engine)
        assert state.released and state.state == "STOPPED"
        assert retained.again.wait(2) and not retained.closed.is_set()
        assert LifecycleIntentStore(db).current().operation_id == first.physical_start_id
    finally:
        service.close()


def test_active_total_uses_last_context_inspection_not_historical_creation(tmp_path):
    class AlreadyClosedContext(WaitingSession):
        async def inspect(self):
            result = await super().inspect()
            result.context_open = False
            return result

    service, db, _store, _member, sessions, _wakes, opened = coordinator(
        tmp_path, session_type=AlreadyClosedContext
    )
    run = service.start(
        "queues_tokens", str(uuid4()), counts={"chromium": 1, "firefox": 0, "webkit": 0}
    )
    service.physical_started(run.physical_start_id)
    confirm_start(db, run.physical_start_id)
    try:
        assert opened[run.engine].wait(3) and sessions[run.engine].again.wait(2)
        state = next(row for row in service.snapshot()["engines"] if row["engine"] == run.engine)
        assert state["created"] == 1
        assert state["active"] == 0
        assert state["sessions"][0]["state"] == "OBSERVED"
    finally:
        service.close()


def test_physical_shutdown_joins_in_progress_scoped_cleanup_without_second_cancel(tmp_path):
    entered, allow_close, scope_finished = Event(), Event(), Event()

    class SlowActivationClose(WaitingSession):
        async def close_activation(self):
            entered.set()
            while not allow_close.is_set():
                await asyncio.sleep(0.005)
            await super().close_activation()
            scope_finished.set()

    service, db, _store, _member, sessions, _wakes, opened = coordinator(
        tmp_path, session_type=SlowActivationClose
    )
    run = service.start(
        "queues_tokens", str(uuid4()), counts={"chromium": 1, "firefox": 0, "webkit": 0}
    )
    service.physical_started(run.physical_start_id)
    confirm_start(db, run.physical_start_id)
    shutdown_done, errors = Event(), []

    def shutdown():
        try:
            asyncio.run(service.shutdown_activation())
        except Exception as error:
            errors.append(type(error))
        finally:
            shutdown_done.set()

    thread = Thread(target=shutdown)
    try:
        assert opened[run.engine].wait(3) and sessions[run.engine].observed.wait(2)
        service.stop(
            run.engine, str(uuid4()), activation_id=run.activation_id, generation=run.generation
        )
        assert entered.wait(2) and sessions[run.engine].closed.wait(2)
        thread.start()
        assert not shutdown_done.wait(0.1)
        allow_close.set()
        assert shutdown_done.wait(3) and scope_finished.is_set()
        assert not errors
    finally:
        allow_close.set()
        if thread.ident is not None:
            thread.join(timeout=3)
        service.close()


@pytest.mark.parametrize(
    "race", ["none", "rotate_read", "revoke_read", "stop_read", "rotate_exchange", "stop_exchange"]
)
def test_actual_member_authority_covers_read_dispatch_and_late_result(tmp_path, monkeypatch, race):
    from boca_socios.browser.boca_auth_protocol import BocaAuthReply
    from boca_socios.integration.boca_login import authenticate_member
    from boca_socios.integration.engine_sessions import EngineSessionCoordinator
    from boca_socios.security.enrollment import MemberEnrollmentService
    from boca_socios.security.member_auth_contract import (
        BocaMemberAuthService,
        PrivateBocaAuthMonitor,
    )

    db, vault, member, store = prepared_store(tmp_path)
    monitor = PrivateBocaAuthMonitor()
    entered, proceed, login_called, queue_opened = Event(), Event(), Event(), Event()
    sessions, wakes = {}, []
    original = BocaMemberAuthService._read_member

    def delayed_read(path, selected, *, authority=None):
        entered.set()
        assert proceed.wait(3)
        return original(path, selected, authority=authority)

    if race.endswith("_read"):
        monkeypatch.setattr(BocaMemberAuthService, "_read_member", staticmethod(delayed_read))

    def mutate(kind):
        if kind == "rotate":
            MemberEnrollmentService(db, vault).rotate_password(
                member, "replacement-offline-credential"
            )
        elif kind == "revoke":
            MemberEnrollmentService(db, vault).revoke_credential(member)
        else:
            service.stop(
                browser.engine,
                str(uuid4()),
                activation_id=browser.activation_id,
                generation=browser.generation,
            )

    class AuthSession(WaitingSession):
        async def prepare_boca_login(self, operation):
            await self.observe_queue()
            observed = parse_queue_page_observation(
                final_url="https://offline.example.invalid/",
                queue_model=None,
                markers=frozenset(),
                observed_at=datetime.now(UTC),
            )
            return BocaAuthReadiness(operation, observed, "a" * 64, 15)

        async def login_boca(self, request):
            login_called.set()
            assert request.password == "existing-encrypted-credential"
            assert monitor.list_summaries() == ()
            if race.endswith("_exchange"):
                mutate(race.split("_")[0])
            return BocaAuthReply(
                request.operation_id,
                request.nonce,
                b'{"token":"offline-access","refreshToken":"offline-refresh"}',
            )

    def factory(identity):
        worker = (
            AuthSession(identity)
            if identity.engine == "browsers_members"
            else WaitingSession(identity)
        )
        sessions[identity.engine] = worker
        if identity.engine == "queues_tokens":
            queue_opened.set()
        return worker

    service = EngineSessionCoordinator(
        store=store,
        wake=wakes.append,
        session_factory=factory,
        authenticate=partial(authenticate_member, db, vault),
        auth_monitor=monitor,
        poll_seconds=0.02,
        open_seconds=0,
        receipt_seconds=2,
    )
    counts = {"chromium": 1, "firefox": 0, "webkit": 0}
    queues = service.start("queues_tokens", str(uuid4()), counts=counts)
    service.physical_started(queues.physical_start_id)
    confirm_start(db, queues.physical_start_id)
    assert queue_opened.wait(3) and sessions[queues.engine].observed.wait(2)
    browser = service.start("browsers_members", str(uuid4()), member_id=member, counts=counts)
    try:
        if race.endswith("_read"):
            assert entered.wait(3)
            mutate(race.split("_")[0])
            proceed.set()
        if race == "none":
            assert login_called.wait(3)
            assert sessions[browser.engine].again.wait(2)
            assert len(monitor.list_summaries()) == 1
            details = service.private_details(
                sessions[browser.engine].identity.session_id, owner_authenticated=True
            )
            assert details.auth is not None
            assert details.phase == "AUTH_TOKENS_OBSERVED_DOM_UNVERIFIED"
        else:
            service._runs[browser.activation_id].future.result(timeout=3)
            assert login_called.is_set() is race.endswith("_exchange")
            assert monitor.list_summaries() == ()
            details = service.private_details(
                sessions[browser.engine].identity.session_id, owner_authenticated=True
            )
            assert details.auth is None
        retained = sessions[queues.engine]
        retained.again.clear()
        assert retained.again.wait(2) and not retained.closed.is_set()
        assert LifecycleIntentStore(db).current().operation_id == queues.physical_start_id
    finally:
        proceed.set()
        service.close()
