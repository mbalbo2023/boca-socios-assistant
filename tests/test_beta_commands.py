"""The callable BETA service runs only synthetic work on temporary SQLite."""

import asyncio
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.domain.policy import TicketIntent
from boca_socios.integration.beta import BetaCoordinator, CommandConflict, CommandState
from boca_socios.integration.command_store import CommandStore
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.panel.local_status import LocalStatusUnavailable, read_local_status
from boca_socios.reservation_guard import ReservationAttemptGuard, ReservationResolution
from boca_socios.storage.database import Database


class Browser:
    def __init__(self):
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.cancelled = False

    async def simulate_general_reservation(self):
        self.calls += 1
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return SimulationOutcome.RESERVED_IN_SIMULATOR


class BetaCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Database(Path(self.directory.name) / "boca.sqlite")
        self.outbox = SqliteNotificationOutbox(self.db)
        self.browser = Browser()
        self.now = 1000.0
        self.service = self.make_service()
        self.service.prepare_storage()
        self.db.create_member("member", "member@example.invalid", "synthetic")
        self.db.create_member("other", "other@example.invalid", "synthetic")
        self.db.create_event("event", "Synthetic event")
        self.intent = TicketIntent("member", "event")
        self.key = str(uuid4())

    def make_service(self, **kwargs):
        return BetaCoordinator(
            database=self.db,
            outbox=self.outbox,
            browser=self.browser,
            clock=lambda: self.now,
            **kwargs,
        )

    async def asyncTearDown(self):
        await self.service.close()

    async def test_begin_status_and_notice_are_real_local_results(self):
        first = await self.service.begin(self.key, self.intent)
        self.assertEqual(first.state, CommandState.ACCEPTED)
        await self.service.wait_idle()
        result = self.service.status(self.key, member_id="member")
        self.assertEqual(result.state, CommandState.COMPLETED)
        self.assertTrue(result.notice_enqueued)
        self.assertEqual(result.external_confirmation, "not_observed")
        self.assertEqual(self.browser.calls, 1)
        with self.db.connection() as connection:
            self.assertEqual(
                connection.execute("SELECT quantity,status FROM ticket_requests").fetchall(),
                [(1, "planned")],
            )
            self.assertEqual(
                connection.execute("SELECT count(*) FROM notification_outbox").fetchone(),
                (1,),
            )

    async def test_repeated_keys_and_member_event_aliases_never_repeat_browser(self):
        snapshots = await asyncio.gather(
            self.service.begin(self.key, self.intent),
            self.service.begin(self.key, self.intent),
            self.service.begin(str(uuid4()), self.intent),
        )
        self.assertEqual({s.command_id for s in snapshots}, {self.key})
        await self.service.wait_idle()
        await self.service.close()
        self.service = self.make_service()
        await self.service.recover()
        again = await self.service.begin(self.key, self.intent)
        self.assertEqual(again.state, CommandState.COMPLETED)
        self.assertEqual(self.browser.calls, 1)

    async def test_conflicting_key_and_wrong_member_cannot_change_command(self):
        await self.service.begin(self.key, self.intent)
        with self.assertRaises(CommandConflict):
            await self.service.begin(self.key, TicketIntent("other", "event"))
        self.assertIsNone(self.service.status(self.key, member_id="other"))
        self.assertIsNone(await self.service.stop(self.key, member_id="other"))
        await self.service.wait_idle()
        with self.db.connection() as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM ticket_requests").fetchone(),
                (1,),
            )

    async def test_stop_before_execution_is_durable_and_idempotent(self):
        await self.service.begin(self.key, self.intent)
        stopped = await self.service.stop(self.key, member_id="member")
        self.assertEqual(stopped.state, CommandState.STOPPED)
        self.assertEqual(await self.service.stop(self.key, member_id="member"), stopped)
        await self.service.wait_idle()
        await self.service.close()
        self.service = self.make_service()
        await self.service.recover()
        self.assertEqual(
            (await self.service.begin(self.key, self.intent)).state,
            CommandState.STOPPED,
        )
        self.assertEqual(self.browser.calls, 0)

    async def test_stop_running_cancels_without_rearming_guard(self):
        self.browser.release.clear()
        await self.service.begin(self.key, self.intent)
        await self.browser.started.wait()
        await self.service.stop(self.key, member_id="member")
        await self.service.wait_idle()
        result = self.service.status(self.key, member_id="member")
        self.assertEqual(result.state, CommandState.STOPPED)
        await self.service.begin(str(uuid4()), self.intent)
        self.assertEqual(self.browser.calls, 1)

    async def test_recovery_does_not_reexecute_ambiguous_running_attempt(self):
        self.service._store.enqueue(self.key, self.intent, now=self.now, max_pending=16)
        record, intent = self.service._store.claim_next(now=self.now)
        ReservationAttemptGuard(self.db).claim_simulation(record.request_id, now=self.now)
        await self.service.recover()
        result = self.service.status(self.key, member_id="member")
        self.assertEqual(result.state, CommandState.NEEDS_REVIEW)
        await self.service.begin(self.key, intent)
        await self.service.wait_idle()
        self.assertEqual(self.browser.calls, 0)

    async def test_recovery_replays_completed_notice_without_browser(self):
        self.service._store.enqueue(self.key, self.intent, now=self.now, max_pending=16)
        record, _ = self.service._store.claim_next(now=self.now)
        guard = ReservationAttemptGuard(self.db)
        claim = guard.claim_simulation(record.request_id, now=self.now)
        guard.resolve(claim, ReservationResolution.SIMULATION_COMPLETED, now=self.now)
        await self.service.recover()
        result = self.service.status(self.key, member_id="member")
        self.assertEqual(result.state, CommandState.COMPLETED)
        self.assertTrue(result.notice_enqueued)
        await self.service.wait_idle()
        await self.service.recover()
        self.assertEqual(self.browser.calls, 0)
        with self.db.connection() as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM notification_outbox").fetchone(),
                (1,),
            )

    async def test_recovery_safely_runs_never_started_accepted_command(self):
        self.service._store.enqueue(self.key, self.intent, now=self.now, max_pending=16)
        await self.service.recover()
        await self.service.wait_idle()
        self.assertEqual(
            self.service.status(self.key, member_id="member").state,
            CommandState.COMPLETED,
        )
        self.assertEqual(self.browser.calls, 1)

    async def test_storage_failure_stops_worker_without_second_browser(self):
        await self.service.begin(self.key, self.intent)
        with self.db.connection() as connection, connection:
            connection.execute("ALTER TABLE beta_commands RENAME TO unavailable_commands")
        await self.service.wait_idle()
        self.assertTrue(self.service.failed)
        self.assertEqual(self.browser.calls, 0)

    async def test_database_injection_is_explicit_and_no_implicit_migration(self):
        self.assertIs(self.outbox.database, self.db)
        with self.assertRaises(ValueError):
            BetaCoordinator(
                database=self.db,
                outbox=SqliteNotificationOutbox(self.db.path),
                browser=self.browser,
            )
        fresh = Path(self.directory.name) / "unprepared.sqlite"
        legacy = SqliteNotificationOutbox(fresh)
        self.assertFalse(fresh.exists())
        self.assertEqual(legacy.database.path, fresh)
        with self.assertRaises(AttributeError):
            self.outbox.database = Database(fresh)

    async def test_invalid_input_and_configuration_fail_before_writes(self):
        with self.assertRaises(ValueError):
            await self.service.begin("invalid", self.intent)
        with self.assertRaises(ValueError):
            await self.service.begin(self.key, TicketIntent("member", "event", 2))
        for limit in (0, True, 101):
            with self.assertRaises(ValueError):
                self.make_service(max_pending=limit)
        with self.db.connection() as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM beta_commands").fetchone(),
                (0,),
            )

    async def test_two_service_instances_share_global_one_browser_claim(self):
        second = self.make_service()
        self.browser.release.clear()
        await self.service.begin(self.key, self.intent)
        await self.browser.started.wait()
        other = await second.begin(str(uuid4()), TicketIntent("other", "event"))
        await second.wait_idle()
        self.assertEqual(self.browser.calls, 1)
        self.assertEqual(
            second.status(other.command_id, member_id="other").state,
            CommandState.ACCEPTED,
        )
        self.browser.release.set()
        await self.service.wait_idle()
        self.assertEqual(self.browser.calls, 2)
        self.assertEqual(
            second.status(other.command_id, member_id="other").state,
            CommandState.COMPLETED,
        )
        await second.close()

    async def test_notice_failure_is_recovered_without_repeating_browser(self):
        with patch.object(self.outbox, "enqueue", side_effect=RuntimeError("private error")):
            await self.service.begin(self.key, self.intent)
            await self.service.wait_idle()
        pending = self.service.status(self.key, member_id="member")
        self.assertEqual(pending.state, CommandState.COMPLETED)
        self.assertFalse(pending.notice_enqueued)
        self.assertTrue(self.service.failed)
        await self.service.recover()
        await self.service.wait_idle()
        self.assertTrue(self.service.status(self.key, member_id="member").notice_enqueued)
        self.assertEqual(self.browser.calls, 1)

    async def test_pending_capacity_rolls_back_new_intent(self):
        from boca_socios.integration.beta import CommandCapacityError

        limited = self.make_service(max_pending=1)
        self.browser.release.clear()
        await limited.begin(self.key, self.intent)
        await self.browser.started.wait()
        with self.assertRaises(CommandCapacityError):
            await limited.begin(str(uuid4()), TicketIntent("other", "event"))
        with self.db.connection() as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM ticket_requests").fetchone(),
                (1,),
            )
        self.browser.release.set()
        await limited.close()

    async def test_timeout_is_terminal_and_never_retried(self):
        timed = self.make_service(timeout_seconds=0.01)
        self.browser.release.clear()
        await timed.begin(self.key, self.intent)
        await timed.wait_idle()
        self.assertEqual(timed.status(self.key, member_id="member").state, CommandState.FAILED)
        await timed.begin(self.key, self.intent)
        await timed.wait_idle()
        self.assertEqual(self.browser.calls, 1)
        await timed.close()

    async def test_timeout_survives_restart_and_new_alias_without_retry_or_notice(self):
        timed = self.make_service(timeout_seconds=0.01)
        self.browser.release.clear()
        await timed.begin(self.key, self.intent)
        await timed.wait_idle()
        self.assertEqual(timed.status(self.key, member_id="member").state, CommandState.FAILED)
        await timed.close()

        restarted = self.make_service()
        await restarted.recover()
        retried = await restarted.begin(str(uuid4()), self.intent)
        await restarted.wait_idle()
        self.assertEqual(retried.command_id, self.key)
        self.assertEqual(retried.state, CommandState.FAILED)
        self.assertEqual(self.browser.calls, 1)
        with self.db.connection() as connection:
            self.assertEqual(
                connection.execute("SELECT quantity FROM ticket_requests").fetchall(), [(1,)]
            )
            self.assertEqual(
                connection.execute("SELECT count(*) FROM notification_outbox").fetchone(),
                (0,),
            )
        await restarted.close()

    async def test_migration_checksum_mismatch_does_not_rewrite_ledger(self):
        with self.db.connection() as connection, connection:
            connection.execute("UPDATE schema_migrations SET checksum='wrong' WHERE version=6")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.service.prepare_storage()
        with self.db.connection() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT checksum FROM schema_migrations WHERE version=6"
                ).fetchone(),
                ("wrong",),
            )

    async def test_close_cancels_and_joins_even_when_stop_persistence_fails(self):
        self.browser.release.clear()
        await self.service.begin(self.key, self.intent)
        await self.browser.started.wait()
        with patch.object(self.service._store, "stop", side_effect=RuntimeError("private")):
            await self.service.close()
        self.assertTrue(self.browser.cancelled)
        self.assertTrue(self.service.failed)
        self.assertTrue(self.service._worker.done())
        self.assertIsNone(self.service._active)

    async def test_alias_key_is_permanently_bound_and_can_stop_canonical_command(self):
        alias = str(uuid4())
        await self.service.begin(self.key, self.intent)
        await self.service.begin(alias, self.intent)
        with self.assertRaises(CommandConflict):
            await self.service.begin(alias, TicketIntent("other", "event"))
        result = await self.service.stop(alias, member_id="member")
        self.assertEqual(result.command_id, self.key)
        self.assertEqual(result.state, CommandState.STOPPED)
        await self.service.wait_idle()
        self.assertEqual(self.browser.calls, 0)

    async def test_unprepared_operations_do_not_create_an_empty_database(self):
        path = Path(self.directory.name) / "absent.sqlite"
        db = Database(path)
        service = BetaCoordinator(
            database=db, outbox=SqliteNotificationOutbox(db), browser=self.browser
        )
        with self.assertRaises(sqlite3.OperationalError):
            service.status(self.key, member_id="member")
        with self.assertRaises(sqlite3.OperationalError):
            await service.begin(self.key, self.intent)
        self.assertFalse(path.exists())
        await service.close()

    async def test_projection_accepts_schema_six_and_rejects_unknown_seven(self):
        snapshot = read_local_status(self.db.path, observed_at=datetime.now(UTC))
        self.assertEqual(snapshot.external_confirmation, "not_observed")
        with self.db.connection() as connection, connection:
            connection.execute(
                "INSERT INTO schema_migrations(version,checksum) VALUES (7,'unknown')"
            )
        with self.assertRaises(LocalStatusUnavailable):
            read_local_status(self.db.path, observed_at=datetime.now(UTC))

    async def test_invalid_member_identity_cannot_disable_scope_or_access_database(self):
        with (
            patch.object(self.service._store, "get") as get,
            patch.object(self.service._store, "stop") as stop,
        ):
            for member in (None, "", " ", 1, True):
                with self.subTest(member=member), self.assertRaises(ValueError):
                    self.service.status(self.key, member_id=member)
                with self.subTest(member=member), self.assertRaises(ValueError):
                    await self.service.stop(self.key, member_id=member)
            get.assert_not_called()
            stop.assert_not_called()

    async def test_command_schema_failure_rolls_back_ddl_and_version(self):
        db = Database(Path(self.directory.name) / "rollback.sqlite")
        ReservationAttemptGuard(db).migrate_simulation()
        with db.connection() as connection, connection:
            connection.execute("CREATE TABLE beta_command_keys(sentinel TEXT)")
            connection.execute("INSERT INTO beta_command_keys VALUES ('synthetic')")
        with self.assertRaises(sqlite3.OperationalError):
            CommandStore(db).migrate()
        with db.connection() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM sqlite_master WHERE name='beta_commands'"
                ).fetchone(),
                (0,),
            )
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM schema_migrations WHERE version=6"
                ).fetchone(),
                (0,),
            )
            self.assertEqual(
                connection.execute("SELECT * FROM beta_command_keys").fetchall(),
                [("synthetic",)],
            )
