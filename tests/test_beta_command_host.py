"""A private server can use one durable loop across separate HTTP requests."""

import asyncio
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch
from uuid import uuid4

from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.domain.policy import TicketIntent
from boca_socios.integration.beta import BetaCoordinator, CommandState
from boca_socios.integration.command_host import BetaCommandHost, CommandResultUnknown
from boca_socios.integration.command_store import CommandStore
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.storage.database import Database


class _Browser:
    def __init__(self) -> None:
        self.calls = 0
        self.started = Event()
        self.release = Event()
        self.release.set()
        self.loops: list[asyncio.AbstractEventLoop] = []
        self.cancelled = False

    async def simulate_general_reservation(self) -> SimulationOutcome:
        self.calls += 1
        self.loops.append(asyncio.get_running_loop())
        self.started.set()
        try:
            while not self.release.is_set():
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return SimulationOutcome.RESERVED_IN_SIMULATOR


class CommandHostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Database(Path(self.directory.name) / "synthetic.sqlite")
        self.outbox = SqliteNotificationOutbox(self.db)
        self.browser = _Browser()
        self.coordinator = self.make_coordinator()
        self.coordinator.prepare_storage()
        self.db.create_member("member", "member@example.invalid", "synthetic")
        self.db.create_member("other", "other@example.invalid", "synthetic")
        self.db.create_event("event", "Synthetic event")

    def make_coordinator(self) -> BetaCoordinator:
        return BetaCoordinator(
            database=self.db, outbox=self.outbox, browser=self.browser, clock=lambda: 1000.0
        )

    def open_host(self, **kwargs: float) -> BetaCommandHost:
        host = BetaCommandHost.start(self.coordinator, **kwargs)
        self.addCleanup(host.close)
        return host

    def wait_state(self, host: BetaCommandHost, key: str, *states: CommandState) -> CommandState:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            snapshot = host.status(key, member_id="member")
            if snapshot is not None and snapshot.state in states:
                return snapshot.state
            time.sleep(0.01)
        self.fail("local command did not reach its expected state")

    def test_separate_requests_share_one_loop_and_one_durable_intent(self) -> None:
        host = self.open_host()
        first_key, alias = str(uuid4()), str(uuid4())
        first = host.begin(first_key, member_id="member", event_id="event")
        self.assertEqual(first.command_id, first_key)
        self.assertEqual(self.wait_state(host, first_key, CommandState.COMPLETED), "completed")
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    lambda key: host.begin(key, member_id="member", event_id="event"),
                    (first_key, alias),
                )
            )
        self.assertEqual({snapshot.command_id for snapshot in responses}, {first_key})
        self.assertEqual(self.browser.calls, 1)
        self.assertEqual(len(set(self.browser.loops)), 1)
        self.assertIsNone(host.status(first_key, member_id="other"))
        self.assertIsNone(host.stop(first_key, member_id="other"))
        with self.db.connection() as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM ticket_requests").fetchone(), (1,)
            )
            self.assertEqual(
                connection.execute("SELECT quantity FROM ticket_requests").fetchone(), (1,)
            )
            self.assertEqual(
                connection.execute("SELECT count(*) FROM notification_outbox").fetchone(), (1,)
            )

    def test_stop_cancels_running_synthetic_worker_and_shutdown_joins(self) -> None:
        self.browser.release.clear()
        host = self.open_host()
        key = str(uuid4())
        host.begin(key, member_id="member", event_id="event")
        self.assertTrue(self.browser.started.wait(2))
        self.assertIn(host.stop(key, member_id="member").state, {"stop_requested", "stopped"})
        self.assertEqual(self.wait_state(host, key, CommandState.STOPPED), "stopped")
        self.assertTrue(self.browser.cancelled)
        host.close()
        self.assertTrue(host.failed)
        with self.assertRaises(RuntimeError):
            host.begin(key, member_id="member", event_id="event")
        self.assertEqual(self.browser.calls, 1)

    def test_startup_recovers_accepted_command_and_never_replays_completed(self) -> None:
        key = str(uuid4())
        CommandStore(self.db).enqueue(
            key, TicketIntent("member", "event"), now=1000, max_pending=16
        )
        host = self.open_host()
        self.assertEqual(self.wait_state(host, key, CommandState.COMPLETED), "completed")
        self.assertEqual(self.browser.calls, 1)
        host.close()
        self.coordinator = self.make_coordinator()
        restarted = self.open_host()
        again = restarted.begin(str(uuid4()), member_id="member", event_id="event")
        self.assertEqual(again.state, CommandState.COMPLETED)
        self.assertEqual(self.browser.calls, 1)

    def test_result_timeout_is_ambiguous_and_same_key_can_be_queried(self) -> None:
        host = self.open_host(request_timeout_seconds=0.02)
        key = str(uuid4())
        original = self.coordinator.begin

        async def delayed(command_id: str, intent: TicketIntent):
            await asyncio.sleep(0.1)
            return await original(command_id, intent)

        with patch.object(self.coordinator, "begin", side_effect=delayed):
            with self.assertRaises(CommandResultUnknown):
                host.begin(key, member_id="member", event_id="event")
        self.assertEqual(self.wait_state(host, key, CommandState.COMPLETED), "completed")
        self.assertEqual(self.browser.calls, 1)

    def test_start_does_not_initialize_or_modify_unprepared_storage(self) -> None:
        fresh = Path(self.directory.name) / "unprepared.sqlite"
        db = Database(fresh)
        service = BetaCoordinator(
            database=db, outbox=SqliteNotificationOutbox(db), browser=self.browser
        )
        with self.assertRaisesRegex(RuntimeError, "recovery failed"):
            BetaCommandHost.start(service)
        self.assertFalse(fresh.exists())

    def test_bad_schema_fails_closed_without_migration(self) -> None:
        with self.db.connection() as connection, connection:
            connection.execute("DROP TABLE beta_commands")
        with self.assertRaisesRegex(RuntimeError, "recovery failed"):
            BetaCommandHost.start(self.coordinator)
        with sqlite3.connect(self.db.path) as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='beta_commands'"
                ).fetchone()
            )


if __name__ == "__main__":
    unittest.main()
