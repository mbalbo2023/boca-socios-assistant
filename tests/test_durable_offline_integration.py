"""SQLite fences local synthetic work; no website, credentials or live runtime."""

from __future__ import annotations

import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from threading import Barrier

import pytest

from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.domain.policy import TicketIntent
from boca_socios.integration import DurableOfflineSimulation
from boca_socios.notify import NotificationRecord, NotificationRequest
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.panel.local_status import read_local_status
from boca_socios.queue import InvalidStateTransition, OfflineQueueSimulator, SimulatorConfig
from boca_socios.reservation_guard import (
    ReservationAttemptGuard,
    ReservationResolution,
    ReservationState,
)
from boca_socios.storage.database import Database

START = datetime(2026, 10, 31, 18, tzinfo=UTC)
INTENT = TicketIntent("member-1", "event-1")


class BrowserDouble:
    def __init__(self, *, failure: BaseException | None = None) -> None:
        self.calls = 0
        self.failure = failure

    async def simulate_general_reservation(self) -> SimulationOutcome:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return SimulationOutcome.RESERVED_IN_SIMULATOR


def _storage(path: Path) -> tuple[Database, SqliteNotificationOutbox]:
    database = Database(path)
    database.migrate()
    database.create_member("member-1", "test@invalid.test", START.isoformat())
    database.create_event("event-1", "Synthetic event")
    outbox = SqliteNotificationOutbox(path)
    outbox.migrate()
    return database, outbox


def _lab(
    database: Database,
    outbox: SqliteNotificationOutbox,
    browser: BrowserDouble,
) -> DurableOfflineSimulation:
    queue = OfflineQueueSimulator(
        SimulatorConfig(event_id="event-1", opens_at=START, closes_at=START + timedelta(hours=1))
    )
    queue.create_session("member-1", "session-1", START)
    queue.join("session-1", START)
    assert queue.admit_next(START) is not None
    lab = DurableOfflineSimulation(
        database=database,
        queue=queue,
        outbox=outbox,
        browser=browser,
        clock=lambda: START.timestamp(),
    )
    lab.prepare_storage()
    return lab


def _run(lab: DurableOfflineSimulation) -> object:
    return asyncio.run(
        lab.run_admitted(
            INTENT, session_id="session-1", at=START, notification_at_seconds=START.timestamp()
        )
    )


def test_restart_replays_completed_simulation_without_second_browser(tmp_path: Path) -> None:
    path = tmp_path / "boca.sqlite3"
    database, outbox = _storage(path)
    first_browser = BrowserDouble()
    first = _run(_lab(database, outbox, first_browser))
    restarted_browser = BrowserDouble()
    replay = _run(_lab(Database(path), SqliteNotificationOutbox(path), restarted_browser))
    assert first == replay
    assert first_browser.calls == 1 and restarted_browser.calls == 0
    request_id = database.request_ticket(INTENT)
    assert ReservationAttemptGuard(database).get(request_id).state is (
        ReservationState.SIMULATION_COMPLETED
    )
    with database.connection() as connection:
        assert connection.execute("SELECT quantity, status FROM ticket_requests").fetchall() == [
            (1, "planned")
        ]
        assert connection.execute("SELECT count(*) FROM notification_outbox").fetchone() == (1,)
    snapshot = read_local_status(path, observed_at=datetime.now(UTC))
    assert snapshot.external_confirmation == "not_observed"


def test_separate_coordinators_racing_share_one_browser_claim(tmp_path: Path) -> None:
    database, outbox = _storage(tmp_path / "boca.sqlite3")
    browsers = [BrowserDouble(), BrowserDouble()]
    labs = [_lab(database, outbox, browser) for browser in browsers]
    barrier = Barrier(2)

    def compete(index: int) -> object:
        barrier.wait(timeout=5)
        try:
            return _run(labs[index])
        except InvalidStateTransition as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, range(2)))
    assert sum(browser.calls for browser in browsers) == 1
    assert any(not isinstance(result, InvalidStateTransition) for result in results)
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM reservation_attempts").fetchone() == (1,)


@pytest.mark.parametrize("failure", [RuntimeError("synthetic failed"), asyncio.CancelledError()])
def test_failure_or_cancellation_never_reopens_browser_claim(
    tmp_path: Path, failure: BaseException
) -> None:
    database, outbox = _storage(tmp_path / "boca.sqlite3")
    browser = BrowserDouble(failure=failure)
    with pytest.raises(type(failure)):
        _run(_lab(database, outbox, browser))
    restarted = BrowserDouble()
    with pytest.raises(InvalidStateTransition):
        _run(_lab(database, outbox, restarted))
    assert browser.calls == 1 and restarted.calls == 0
    request_id = database.request_ticket(INTENT)
    assert ReservationAttemptGuard(database).get(request_id).state is ReservationState.SIMULATION_FAILED
    assert outbox.claim_ready(now=START.timestamp()) == ()


def test_crash_after_claim_is_not_retried_by_new_coordinator(tmp_path: Path) -> None:
    database, outbox = _storage(tmp_path / "boca.sqlite3")
    browser = BrowserDouble()
    lab = _lab(database, outbox, browser)
    guard = ReservationAttemptGuard(database)
    request_id = database.request_ticket(INTENT)
    assert guard.claim(request_id, now=START.timestamp()) is not None
    with pytest.raises(InvalidStateTransition):
        _run(lab)
    assert browser.calls == 0
    assert guard.mark_overdue(now=START.timestamp() + 121) == 1
    with pytest.raises(InvalidStateTransition):
        _run(_lab(database, outbox, browser))
    assert browser.calls == 0


def test_notice_failure_can_replay_notice_without_repeating_browser(tmp_path: Path) -> None:
    database, outbox = _storage(tmp_path / "boca.sqlite3")

    class FailingOutbox(SqliteNotificationOutbox):
        def enqueue(self, request: NotificationRequest, *, now: float) -> NotificationRecord:
            raise RuntimeError("synthetic outbox unavailable")

    browser = BrowserDouble()
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        _run(_lab(database, FailingOutbox(database.path), browser))
    restarted = BrowserDouble()
    _run(_lab(database, outbox, restarted))
    assert browser.calls == 1 and restarted.calls == 0
    assert len(outbox.claim_ready(now=START.timestamp())) == 1


def test_opt_in_schema_preserves_existing_claims_and_original_checksum(tmp_path: Path) -> None:
    database, _ = _storage(tmp_path / "boca.sqlite3")
    guard = ReservationAttemptGuard(database)
    guard.migrate()
    request_id = database.request_ticket(INTENT)
    claim = guard.claim(request_id, now=1000)
    assert claim is not None
    previous = guard.resolve(claim, ReservationResolution.PROVIDER_ACK_REPORTED, now=1001)
    guard.migrate_simulation()
    guard.migrate_simulation()
    assert guard.get(request_id) == previous
    assert guard.claim(request_id, now=1002) is None
    sql = files("boca_socios.storage.migrations").joinpath("0003_reservation_guard.sql").read_text()
    with database.connection() as connection:
        assert connection.execute("SELECT checksum FROM schema_migrations WHERE version=3").fetchone() == (
            hashlib.sha256(sql.encode()).hexdigest(),
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT count(*) FROM schema_migrations WHERE version=5").fetchone() == (1,)


def test_failed_schema_upgrade_rolls_back_without_erasing_prior_claim(tmp_path: Path) -> None:
    database, _ = _storage(tmp_path / "boca.sqlite3")
    guard = ReservationAttemptGuard(database)
    guard.migrate()
    request_id = database.request_ticket(INTENT)
    assert guard.claim(request_id, now=1000) is not None
    with database.connection() as connection, connection:
        connection.execute("CREATE TABLE reservation_attempts_simulation (occupied TEXT)")
    with pytest.raises(Exception):
        guard.migrate_simulation()
    assert guard.get(request_id).state is ReservationState.IN_FLIGHT
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM schema_migrations WHERE version=5").fetchone() == (0,)
