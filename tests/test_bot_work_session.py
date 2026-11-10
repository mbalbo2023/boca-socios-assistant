"""Durable boundaries of a single authenticated, on-demand simulation session."""

from __future__ import annotations

import asyncio
import base64
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
        LifecycleIntentStore(database).request("bot", "start", start_id)
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
        store.request("bot", "start", operation_id)
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
    ledger.request("bot", "start", start_id)
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
    ledger.request("bot", "start", start_id)
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
    ledger.request("bot", "start", start_id)
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
