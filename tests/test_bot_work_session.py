"""Durable boundaries of a single authenticated, on-demand simulation session."""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.domain.policy import TicketIntent
from boca_socios.integration import beta
from boca_socios.integration.command_store import CommandState, CommandStore
from boca_socios.integration.operational import LocalBetaRuntime
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.panel.lifecycle_intents import LifecycleIntentStore, host_marker
from boca_socios.panel.worker_activity import read_worker_activity
from boca_socios.storage.database import Database


class Browser:
    calls = 0

    async def simulate_general_reservation(self) -> SimulationOutcome:
        self.calls += 1
        await asyncio.sleep(0)
        return SimulationOutcome.RESERVED_IN_SIMULATOR


@pytest.fixture
def prepared(tmp_path: Path):
    key = tmp_path / "key"
    key.write_bytes(base64.b64encode(b"k" * 32) + b"\n")
    key.chmod(0o400)
    path = tmp_path / "boca.sqlite3"
    browser = Browser()
    initialized = LocalBetaRuntime.start(
        database_path=path, key_file=key, browser=browser, initialize_new=True
    )
    initialized.database.create_member("member", "test@example.invalid", "synthetic")
    initialized.database.create_event("event", "Synthetic")
    initialized.close()
    return Database(path), key, browser


def confirm_start(database: Database, operation_id: str) -> None:
    with database.connection() as connection, connection:
        for status in ("CLAIMED", "APPLIED"):
            connection.execute(
                "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                host_marker(operation_id, "bot", "start", status),
            )


@pytest.mark.parametrize(
    "outcome", ["NO_EVENT_OBSERVED", "QUEUE_INACTIVE", "CHECK_FAILED", "TARGET_OBSERVED"]
)
def test_automatic_observation_terminal_derives_one_stop_without_faking_work(prepared, outcome):
    database, _, _ = prepared
    ledger = LifecycleIntentStore(database)
    start = str(uuid4())
    ledger.request("bot", "start", start, on_demand=True)
    confirm_start(database, start)
    ledger.record_automatic_check(start, outcome)
    stopped = ledger.request_work_stop(start)
    assert stopped is not None and stopped.work_start_id == start
    assert stopped.target == "stop" and stopped.status == "REQUESTED"
    assert ledger.request_work_stop(start) == stopped
    if outcome == "NO_EVENT_OBSERVED":
        activity = read_worker_activity(database.path, observed_at=datetime.now(UTC))
        assert any("no hay eventos" in item.message for item in activity.events)
        assert any("comprobación finalizada" in item.message for item in activity.events)
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM beta_commands").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM ticket_requests").fetchone() == (0,)


@pytest.mark.parametrize("outcome", ["QUEUE_ACTIVE", "PREQUEUE"])
def test_waiting_queue_is_not_a_terminal_or_absence_receipt(prepared, outcome):
    database, _, _ = prepared
    ledger = LifecycleIntentStore(database)
    start = str(uuid4())
    ledger.request("bot", "start", start, on_demand=True)
    confirm_start(database, start)
    ledger.record_automatic_check(start, outcome)
    assert ledger.request_work_stop(start) is None


def test_completed_simulation_does_not_stop_an_active_automatic_queue(prepared):
    database, _, browser = prepared
    database.create_member("second-member", "second@example.invalid", "synthetic")
    ledger = LifecycleIntentStore(database)
    start = str(uuid4())
    ledger.request("bot", "start", start, on_demand=True)
    confirm_start(database, start)
    ledger.record_automatic_check(start, "QUEUE_ACTIVE")
    wakes = []
    coordinator = beta.BetaCoordinator(
        database=database,
        outbox=SqliteNotificationOutbox(database),
        browser=browser,
        bot_session=beta.OnDemandBotSession(ledger, lambda: None, wakes.append),
    )

    async def run():
        try:
            await coordinator.begin(str(uuid4()), TicketIntent("member", "event"))
            await coordinator.wait_idle()
            assert ledger.current().target == "start"
            assert wakes == []
            second = str(uuid4())
            await coordinator.begin(second, TicketIntent("second-member", "event"))
            await coordinator.wait_idle()
            assert (
                coordinator.status(second, member_id="second-member").state
                is CommandState.COMPLETED
            )
            assert browser.calls == 2 and wakes == []
            ledger.record_automatic_check(start, "TARGET_OBSERVED")
            assert ledger.request_work_stop(start) is not None
            with pytest.raises(RuntimeError):
                await coordinator.begin(str(uuid4()), TicketIntent("member", "event"))
        finally:
            await coordinator.close()

    asyncio.run(run())


def test_automatic_observation_cannot_complete_other_or_unconfirmed_start(prepared):
    database, _, _ = prepared
    ledger = LifecycleIntentStore(database)
    start = str(uuid4())
    ledger.request("bot", "start", start, on_demand=True)
    with pytest.raises(RuntimeError):
        ledger.record_automatic_check(start, "NO_EVENT_OBSERVED")
    confirm_start(database, start)
    with pytest.raises(RuntimeError):
        ledger.record_automatic_check(str(uuid4()), "NO_EVENT_OBSERVED")
    with pytest.raises(ValueError):
        ledger.record_automatic_check(start, "fake-provider-success")


def test_start_requires_worker_before_creating_thread_and_retry_can_succeed(prepared):
    database, key, browser = prepared
    ready = False

    def require_worker() -> None:
        if not ready:
            raise RuntimeError("worker unavailable")

    session = beta.OnDemandBotSession(
        ledger=LifecycleIntentStore(database), check_worker=require_worker, wake=lambda _uuid: None
    )
    service = LocalBetaRuntime.start(
        database_path=database.path,
        key_file=key,
        browser=browser,
        initial_engine_stopped=True,
        bot_session=session,
    )
    try:
        assert service.ready and service.commands.engine_stopped
        with pytest.raises(RuntimeError, match="START"):
            service.commands.start_engine()
        start_id = str(uuid4())
        LifecycleIntentStore(database).request("bot", "start", start_id, on_demand=True)
        with database.connection() as connection, connection:
            connection.execute(
                "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                host_marker(start_id, "bot", "start", "CLAIMED"),
            )
        with pytest.raises(RuntimeError, match="worker unavailable"):
            service.commands.start_engine()
        assert service.ready and service.commands.engine_stopped
        ready = True
        assert service.commands.start_engine()
        assert service.commands.engine_running and browser.calls == 0
    finally:
        service.close()


def test_commands_need_applied_start_and_live_worker_before_durable_enqueue(prepared):
    database, _key, browser = prepared
    store = LifecycleIntentStore(database)
    ready = False

    def require_worker() -> None:
        if not ready:
            raise RuntimeError("worker unavailable")

    session = beta.OnDemandBotSession(
        ledger=store, check_worker=require_worker, wake=lambda _uuid: None
    )
    coordinator = beta.BetaCoordinator(
        database=database,
        outbox=SqliteNotificationOutbox(database),
        browser=browser,
        bot_session=session,
    )
    operation_id, command_id = str(uuid4()), str(uuid4())
    intent = TicketIntent("member", "event")

    async def exercise() -> None:
        nonlocal ready
        ready = True
        store.request("bot", "start", operation_id, on_demand=True)
        with pytest.raises(RuntimeError):
            await coordinator.begin(command_id, intent)
        ready = False
        confirm_start(database, operation_id)
        with pytest.raises(RuntimeError):
            await coordinator.begin(command_id, intent)
        assert coordinator.status(command_id, member_id="member") is None
        assert browser.calls == 0
        await coordinator.close()

    asyncio.run(exercise())


def test_real_work_closes_only_its_session_after_durable_result_and_blocks_late_commands(prepared):
    database, _key, browser = prepared
    ledger = LifecycleIntentStore(database)
    start_id = str(uuid4())
    ledger.request("bot", "start", start_id, on_demand=True)
    confirm_start(database, start_id)
    woke = []
    session = beta.OnDemandBotSession(ledger=ledger, check_worker=lambda: None, wake=woke.append)
    coordinator = beta.BetaCoordinator(
        database=database,
        outbox=SqliteNotificationOutbox(database),
        browser=browser,
        bot_session=session,
    )

    async def exercise() -> None:
        await coordinator.recover()
        await coordinator.wait_idle()
        assert woke == []
        key = str(uuid4())
        await coordinator.begin(key, TicketIntent("member", "event"))
        await coordinator.wait_idle()
        result = coordinator.status(key, member_id="member")
        assert result and result.state == CommandState.COMPLETED and result.notice_enqueued
        current = ledger.current()
        assert current and current.target == "stop" and current.status == "REQUESTED"
        assert woke == [current.operation_id] and woke[0] != start_id
        with pytest.raises(RuntimeError):
            await coordinator.begin(str(uuid4()), TicketIntent("member", "event"))
        assert browser.calls == 1
        await coordinator.close()

    asyncio.run(exercise())


def test_completed_work_activity_contains_actual_queue_steps_and_correlated_automatic_stop(
    prepared,
):
    database, _key, browser = prepared
    ledger = LifecycleIntentStore(database)
    start_id = str(uuid4())
    ledger.request("bot", "start", start_id, on_demand=True)
    confirm_start(database, start_id)
    coordinator = beta.BetaCoordinator(
        database=database,
        outbox=SqliteNotificationOutbox(database),
        browser=browser,
        bot_session=beta.OnDemandBotSession(ledger, lambda: None, lambda _operation: None),
    )

    async def exercise():
        await coordinator.begin(str(uuid4()), TicketIntent("member", "event"))
        await coordinator.wait_idle()
        await coordinator.close()

    asyncio.run(exercise())
    snapshot = read_worker_activity(database.path, observed_at=datetime.now(UTC))
    messages = [event.message for event in snapshot.events]
    queue = [message for message in messages if message.startswith("Cola simulada:")]
    assert queue == [
        "Cola simulada: solicitud creada.",
        "Cola simulada: solicitud en espera.",
        "Cola simulada: admisión local registrada.",
        "Cola simulada: solicitud cerrada.",
    ]
    assert any(
        "detención automática" in event.message and event.source == "simulation"
        for event in snapshot.events
    )
    assert any(event.message == "Solicitado: inicio del bot." for event in snapshot.events)
    assert start_id not in repr(snapshot)
    assert "member" not in repr(snapshot)


@pytest.mark.parametrize("cancel", [False, True])
def test_interrupted_work_activity_never_claims_a_closed_successful_queue(prepared, cancel):
    database, _key, _browser = prepared

    class InterruptedBrowser:
        async def simulate_general_reservation(self):
            if cancel:
                raise asyncio.CancelledError
            raise RuntimeError("private-provider-detail")

    coordinator = beta.BetaCoordinator(
        database=database,
        outbox=SqliteNotificationOutbox(database),
        browser=InterruptedBrowser(),
    )

    async def exercise():
        await coordinator.begin(str(uuid4()), TicketIntent("member", "event"))
        await coordinator.wait_idle()
        await coordinator.close()

    asyncio.run(exercise())
    snapshot = read_worker_activity(database.path, observed_at=datetime.now(UTC))
    messages = [event.message for event in snapshot.events]
    assert "Cola simulada: solicitud cerrada." not in messages
    expected = (
        "Cola simulada: solicitud cancelada."
        if cancel
        else "Cola simulada: ejecución interrumpida."
    )
    assert expected in messages
    assert "private-provider-detail" not in repr(snapshot)


def test_new_explicit_session_reconciles_uncertain_history_without_replaying(prepared):
    database, _key, browser = prepared
    store = CommandStore(database)
    key = str(uuid4())
    store.enqueue(key, TicketIntent("member", "event"), now=0, max_pending=2)
    woke = []
    session = beta.OnDemandBotSession(
        ledger=LifecycleIntentStore(database), check_worker=lambda: None, wake=woke.append
    )
    coordinator = beta.BetaCoordinator(
        database=database,
        outbox=SqliteNotificationOutbox(database),
        browser=browser,
        bot_session=session,
    )

    async def exercise() -> None:
        await coordinator.recover()
        await coordinator.wait_idle()
        result = coordinator.status(key, member_id="member")
        assert result and result.state is CommandState.STOPPED
        assert browser.calls == 0 and woke == []
        await coordinator.close()

    asyncio.run(exercise())


def test_owner_stop_preempts_a_second_accepted_command_in_the_claim_transaction(prepared):
    database, _key, _browser = prepared
    ledger = LifecycleIntentStore(database)
    start_id, human_stop = str(uuid4()), str(uuid4())
    ledger.request("bot", "start", start_id, on_demand=True)
    confirm_start(database, start_id)
    database.create_event("next", "Second synthetic event")
    woke = []
    session = beta.OnDemandBotSession(ledger=ledger, check_worker=lambda: None, wake=woke.append)

    async def exercise() -> None:
        in_browser, release = asyncio.Event(), asyncio.Event()

        class PausedBrowser:
            calls = 0

            async def simulate_general_reservation(self) -> SimulationOutcome:
                self.calls += 1
                in_browser.set()
                await release.wait()
                return SimulationOutcome.RESERVED_IN_SIMULATOR

        browser = PausedBrowser()
        coordinator = beta.BetaCoordinator(
            database=database,
            outbox=SqliteNotificationOutbox(database),
            browser=browser,
            bot_session=session,
        )
        first, second = str(uuid4()), str(uuid4())
        await coordinator.begin(first, TicketIntent("member", "event"))
        await asyncio.wait_for(in_browser.wait(), 1)
        await coordinator.begin(second, TicketIntent("member", "next"))
        ledger.request("bot", "stop", human_stop, on_demand=True)
        release.set()
        await coordinator.wait_idle()
        result = coordinator.status(second, member_id="member")
        assert result and result.state == CommandState.STOPPED
        assert browser.calls == 1 and woke == []
        current = ledger.current()
        assert current and current.operation_id == human_stop
        await coordinator.close()

    asyncio.run(exercise())


def test_prior_applied_start_cannot_restart_an_engine_over_its_private_socket(prepared):
    database, key, browser = prepared
    ledger = LifecycleIntentStore(database)
    start_id = str(uuid4())
    ledger.request("bot", "start", start_id, on_demand=True)
    confirm_start(database, start_id)
    session = beta.OnDemandBotSession(
        ledger=ledger, check_worker=lambda: None, wake=lambda _id: None
    )
    service = LocalBetaRuntime.start(
        database_path=database.path,
        key_file=key,
        browser=browser,
        initial_engine_stopped=True,
        bot_session=session,
    )
    try:
        with pytest.raises(RuntimeError, match="START"):
            service.commands.start_engine()
        assert service.ready and service.commands.engine_stopped and browser.calls == 0
    finally:
        service.close()


@pytest.mark.parametrize("status", ["CLAIMED", "APPLIED"])
def test_legacy_start_never_authorizes_on_demand_motor_or_work(prepared, status):
    database, key, browser = prepared
    ledger = LifecycleIntentStore(database)
    legacy_id = str(uuid4())
    ledger.request("bot", "start", legacy_id)
    with database.connection() as connection, connection:
        for phase in ("CLAIMED", "APPLIED"):
            connection.execute(
                "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                host_marker(legacy_id, "bot", "start", phase),
            )
            if phase == status:
                break

    def unexpected_socket_access() -> None:
        pytest.fail("legacy receipt reached the on-demand worker")

    session = beta.OnDemandBotSession(
        ledger=ledger, check_worker=unexpected_socket_access, wake=lambda _id: None
    )
    service = LocalBetaRuntime.start(
        database_path=database.path,
        key_file=key,
        browser=browser,
        initial_engine_stopped=True,
        bot_session=session,
    )
    try:
        with pytest.raises(RuntimeError, match="START"):
            if status == "CLAIMED":
                service.commands.start_engine()
            else:
                session.require_start("APPLIED")
        assert service.ready and service.commands.engine_stopped and browser.calls == 0
    finally:
        service.close()
