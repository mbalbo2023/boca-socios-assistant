"""Cross-PR regression checks for the opt-in, entirely local simulation."""

from __future__ import annotations

import asyncio
import base64
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from boca_socios.browser.contracts import SimulationOutcome, SimulationReceipt
from boca_socios.domain.policy import TicketIntent
from boca_socios.integration import OfflineSimulation
from boca_socios.notify import DeliveryState, NotificationOutbox
from boca_socios.queue import InvalidStateTransition, OfflineQueueSimulator, SimulatorConfig
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.storage.database import Database

START = datetime(2026, 10, 28, 18, tzinfo=UTC)


class FakeBrowser:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.calls = 0
        self.fail_first = fail_first

    async def simulate_general_reservation(self) -> SimulationOutcome:
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise RuntimeError("synthetic screen failed")
        return SimulationOutcome.RESERVED_IN_SIMULATOR


def setup_lab(
    tmp_path: Path, *, fail_first: bool = False
) -> tuple[OfflineSimulation, Database, OfflineQueueSimulator, NotificationOutbox, FakeBrowser]:
    database = Database(tmp_path / "simulated.sqlite3")
    database.migrate()
    database.create_member("member-1", "example@invalid.test", "2026-10-28T18:00:00Z")
    database.create_event("event-1", "Partido ficticio")
    queue = OfflineQueueSimulator(
        SimulatorConfig(event_id="event-1", opens_at=START, closes_at=START + timedelta(hours=1))
    )
    queue.create_session("member-1", "session-1", START)
    queue.create_session("member-1", "session-2", START)
    queue.join("session-1", START)
    assert queue.admit_next(START) is not None
    outbox = NotificationOutbox()
    browser = FakeBrowser(fail_first=fail_first)
    return (
        OfflineSimulation(database=database, queue=queue, outbox=outbox, browser=browser),
        database,
        queue,
        outbox,
        browser,
    )


def test_all_modules_share_one_intent_and_safe_notice(tmp_path: Path) -> None:
    lab, database, queue, outbox, browser = setup_lab(tmp_path)
    intent = TicketIntent("member-1", "event-1")
    receipt = asyncio.run(
        lab.run_admitted(intent, session_id="session-2", at=START, notification_at_seconds=0)
    )

    assert receipt.outcome is SimulationOutcome.RESERVED_IN_SIMULATOR
    assert queue.request_count == 1
    assert queue.session_count == 2
    assert browser.calls == 1
    assert database.request_ticket(intent) == receipt.request_id
    with database.connection() as connection:
        rows = connection.execute(
            "SELECT request_id, quantity, status FROM ticket_requests"
        ).fetchall()
    assert rows == [(receipt.request_id, 1, "planned")]
    assert len(outbox.records()) == 1
    claims = outbox.run_dry_run(now=1)
    assert len(claims) == 1
    assert "Simulación" in claims[0].message
    assert "member-1" not in claims[0].message
    assert outbox.records()[0].state is DeliveryState.ACCEPTED

    with pytest.raises(InvalidStateTransition):
        asyncio.run(
            lab.run_admitted(intent, session_id="session-1", at=START, notification_at_seconds=2)
        )
    assert browser.calls == 1
    assert len(outbox.records()) == 1


def test_retry_after_fake_browser_failure_reuses_only_one_intent(tmp_path: Path) -> None:
    lab, database, queue, outbox, browser = setup_lab(tmp_path, fail_first=True)
    intent = TicketIntent("member-1", "event-1")
    with pytest.raises(RuntimeError, match="synthetic screen failed"):
        asyncio.run(
            lab.run_admitted(intent, session_id="session-1", at=START, notification_at_seconds=0)
        )
    assert outbox.records() == ()
    assert queue.snapshot("session-1").state.value == "admitted"
    original_id = database.request_ticket(intent)

    receipt = asyncio.run(
        lab.run_admitted(intent, session_id="session-2", at=START, notification_at_seconds=1)
    )
    assert receipt.request_id == original_id
    assert browser.calls == 2
    assert len(outbox.records()) == 1
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM ticket_requests").fetchone() == (1,)


def test_unadmitted_wrong_member_expired_and_invalid_quantity_fail_closed(tmp_path: Path) -> None:
    lab, database, queue, outbox, browser = setup_lab(tmp_path)
    for intent, at in (
        (TicketIntent("member-1", "other-event"), START),
        (TicketIntent("different-member", "event-1"), START),
        (TicketIntent("member-1", "event-1", quantity=2), START),
    ):
        with pytest.raises((ValueError, InvalidStateTransition)):
            asyncio.run(
                lab.run_admitted(intent, session_id="session-1", at=at, notification_at_seconds=0)
            )
    with pytest.raises(InvalidStateTransition):
        asyncio.run(
            lab.run_admitted(
                TicketIntent("member-1", "event-1"),
                session_id="session-1",
                at=START + timedelta(minutes=6),
                notification_at_seconds=1,
            )
        )
    assert browser.calls == 0
    assert outbox.records() == ()
    assert queue.request_count == 1
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM ticket_requests").fetchone() == (0,)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO ticket_requests(request_id, member_id, event_id, quantity) "
                "VALUES ('invalid', 'member-1', 'event-1', 2)"
            )


def test_invalid_session_or_identity_does_not_advance_shared_clock(tmp_path: Path) -> None:
    lab, database, queue, outbox, browser = setup_lab(tmp_path)
    for intent, session_id in (
        (TicketIntent("member-1", "event-1"), "unknown-session"),
        (TicketIntent("different-member", "event-1"), "session-1"),
    ):
        with pytest.raises((KeyError, InvalidStateTransition)):
            asyncio.run(
                lab.run_admitted(
                    intent,
                    session_id=session_id,
                    at=START + timedelta(minutes=6),
                    notification_at_seconds=0,
                )
            )
        assert queue.snapshot("session-1").state.value == "admitted"
        assert browser.calls == 0
        assert outbox.records() == ()
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM ticket_requests").fetchone() == (0,)
    assert (
        asyncio.run(
            lab.run_admitted(
                TicketIntent("member-1", "event-1"),
                session_id="session-2",
                at=START,
                notification_at_seconds=0,
            )
        ).outcome
        is SimulationOutcome.RESERVED_IN_SIMULATOR
    )


def test_invalid_notification_time_fails_before_browser_or_database(tmp_path: Path) -> None:
    lab, database, queue, outbox, browser = setup_lab(tmp_path)
    with pytest.raises(ValueError, match="notification time"):
        asyncio.run(
            lab.run_admitted(
                TicketIntent("member-1", "event-1"),
                session_id="session-1",
                at=START,
                notification_at_seconds=float("nan"),
            )
        )
    assert queue.snapshot("session-1").state.value == "admitted"
    assert browser.calls == 0 and outbox.records() == ()
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM ticket_requests").fetchone() == (0,)


def test_two_aliases_cannot_run_the_same_local_browser_attempt_concurrently(
    tmp_path: Path,
) -> None:
    _, database, queue, outbox, _ = setup_lab(tmp_path)

    class PausingBrowser:
        def __init__(self) -> None:
            self.calls = 0
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def simulate_general_reservation(self) -> SimulationOutcome:
            self.calls += 1
            self.entered.set()
            await self.release.wait()
            return SimulationOutcome.RESERVED_IN_SIMULATOR

    browser = PausingBrowser()
    lab = OfflineSimulation(database=database, queue=queue, outbox=outbox, browser=browser)
    intent = TicketIntent("member-1", "event-1")

    async def race() -> list[object]:
        first = asyncio.create_task(
            lab.run_admitted(intent, session_id="session-1", at=START, notification_at_seconds=0)
        )
        await asyncio.wait_for(browser.entered.wait(), timeout=5)
        second = asyncio.create_task(
            lab.run_admitted(intent, session_id="session-2", at=START, notification_at_seconds=0)
        )
        await asyncio.sleep(0)
        browser.release.set()
        return await asyncio.gather(first, second, return_exceptions=True)

    results = asyncio.run(race())
    assert browser.calls == 1
    assert sum(isinstance(item, InvalidStateTransition) for item in results) == 1
    assert sum(isinstance(item, SimulationReceipt) for item in results) == 1
    assert queue.snapshot("session-1").state.value == "closed"
    assert len(outbox.records()) == 1
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM ticket_requests").fetchone() == (1,)


def test_vault_and_database_survive_restart_with_separate_key(tmp_path: Path) -> None:
    key_dir = tmp_path / "private-key"
    key_dir.mkdir(mode=0o700)
    key_path = key_dir / "master"
    key_path.write_bytes(base64.b64encode(os.urandom(32)))
    key_path.chmod(0o600)
    first_vault = CredentialVault.from_secret_file(key_path)
    db_path = tmp_path / "data" / "boca.sqlite3"
    first_database = Database(db_path)
    first_database.migrate()
    first_database.create_member("member-1", "example@invalid.test", "2026-10-28T00:00:00Z")
    first_database.save_credential(
        "member-1", first_vault.seal("only-a-test-value", member_id="member-1")
    )

    reopened = Database(db_path).get_credential("member-1")
    assert reopened is not None
    assert b"only-a-test-value" not in reopened.ciphertext
    assert CredentialVault.from_secret_file(key_path).open(reopened, member_id="member-1") == (
        "only-a-test-value"
    )
    with pytest.raises(InvalidTag):
        CredentialVault(os.urandom(32)).open(reopened, member_id="member-1")
    key_path.chmod(0o644)
    with pytest.raises(ValueError, match="readable by other identities"):
        CredentialVault.from_secret_file(key_path)
