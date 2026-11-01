"""Local lifecycle tests use only a disposable Boca-only SQLite and test key."""

import asyncio
import base64
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from uuid import uuid4

from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.integration.beta import CommandState
from boca_socios.integration.operational import (
    LocalBetaRuntime,
    LocalRuntimeUnavailable,
    validate_existing_beta_storage,
)


class _SyntheticBrowser:
    def __init__(self) -> None:
        self.calls = 0
        self.started = Event()
        self.release = Event()
        self.release.set()
        self.cancelled = False

    async def simulate_general_reservation(self) -> SimulationOutcome:
        self.calls += 1
        self.started.set()
        try:
            while not self.release.is_set():
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return SimulationOutcome.RESERVED_IN_SIMULATOR


class LocalBetaRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db_path = Path(self.directory.name) / "boca.sqlite3"
        self.key_path = Path(self.directory.name) / "boca_master_key"
        self.key_path.write_bytes(base64.b64encode(b"k" * 32) + b"\n")
        self.key_path.chmod(0o400)
        self.browser = _SyntheticBrowser()

    def start(self, *, initialize_new: bool) -> LocalBetaRuntime:
        runtime = LocalBetaRuntime.start(
            database_path=self.db_path,
            key_file=self.key_path,
            browser=self.browser,
            initialize_new=initialize_new,
        )
        self.addCleanup(runtime.close)
        return runtime

    def wait_state(self, runtime: LocalBetaRuntime, key: str, state: CommandState) -> None:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            snapshot = runtime.commands.status(key, member_id="member")
            if snapshot is not None and snapshot.state is state:
                return
            time.sleep(0.01)
        self.fail("local command did not settle")

    def test_first_install_is_explicit_and_existing_restart_is_read_only(self) -> None:
        with self.assertRaises(LocalRuntimeUnavailable):
            self.start(initialize_new=False)
        self.assertFalse(self.db_path.exists())
        runtime = self.start(initialize_new=True)
        self.assertTrue(runtime.ready)
        runtime.database.create_member("member", "member@example.invalid", "synthetic")
        runtime.database.create_event("event", "Synthetic event")
        key = str(uuid4())
        runtime.commands.begin(key, member_id="member", event_id="event")
        self.wait_state(runtime, key, CommandState.COMPLETED)
        runtime.close()

        with sqlite3.connect(self.db_path) as connection:
            before = connection.execute(
                "SELECT version, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
        restarted = self.start(initialize_new=False)
        self.assertTrue(restarted.ready)
        self.assertEqual(
            restarted.commands.begin(str(uuid4()), member_id="member", event_id="event").state,
            CommandState.COMPLETED,
        )
        self.assertEqual(self.browser.calls, 1)
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT version, checksum FROM schema_migrations ORDER BY version"
                ).fetchall(),
                before,
            )
            self.assertEqual(
                connection.execute("SELECT quantity FROM ticket_requests").fetchone(), (1,)
            )

    def test_refuses_existing_file_even_in_first_install_mode(self) -> None:
        self.db_path.write_bytes(b"existing Boca data sentinel")
        with self.assertRaises(LocalRuntimeUnavailable):
            self.start(initialize_new=True)
        self.assertEqual(self.db_path.read_bytes(), b"existing Boca data sentinel")

    def test_bad_key_is_rejected_before_first_install_write(self) -> None:
        self.key_path.chmod(0o600)
        self.key_path.write_text("not a key")
        with self.assertRaises(ValueError):
            self.start(initialize_new=True)
        self.assertFalse(self.db_path.exists())

    def test_existing_checksum_drift_fails_without_repair_or_replacement(self) -> None:
        self.start(initialize_new=True).close()
        with sqlite3.connect(self.db_path) as connection, connection:
            connection.execute("UPDATE schema_migrations SET checksum='wrong' WHERE version=6")
            connection.execute(
                "INSERT INTO members(member_id,email,consent_recorded_at) VALUES ('sentinel','s@example.invalid','synthetic')"
            )
        with self.assertRaises(LocalRuntimeUnavailable):
            self.start(initialize_new=False)
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT checksum FROM schema_migrations WHERE version=6"
                ).fetchone(),
                ("wrong",),
            )
            self.assertEqual(
                connection.execute("SELECT member_id FROM members").fetchone(), ("sentinel",)
            )

    def test_symlink_and_partial_schema_are_not_adopted(self) -> None:
        target = Path(self.directory.name) / "other.sqlite3"
        target.write_bytes(b"unrelated")
        self.db_path.symlink_to(target)
        with self.assertRaises(LocalRuntimeUnavailable):
            validate_existing_beta_storage(self.db_path)
        with self.assertRaises(LocalRuntimeUnavailable):
            self.start(initialize_new=True)
        self.db_path.unlink()
        self.start(initialize_new=True).close()
        with sqlite3.connect(self.db_path) as connection, connection:
            connection.execute("DROP TABLE beta_command_keys")
        with self.assertRaises(LocalRuntimeUnavailable):
            self.start(initialize_new=False)

    def test_close_cancels_local_worker_without_external_call(self) -> None:
        self.browser.release.clear()
        runtime = self.start(initialize_new=True)
        runtime.database.create_member("member", "member@example.invalid", "synthetic")
        runtime.database.create_event("event", "Synthetic event")
        key = str(uuid4())
        runtime.commands.begin(key, member_id="member", event_id="event")
        self.assertTrue(self.browser.started.wait(2))
        runtime.close()
        self.assertFalse(runtime.ready)
        self.assertTrue(self.browser.cancelled)
        self.assertEqual(self.browser.calls, 1)


if __name__ == "__main__":
    unittest.main()
