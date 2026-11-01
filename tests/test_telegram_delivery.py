"""Telegram boundary tests use a fake HTTP connection and temporary SQLite only."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from boca_socios.notify.outbox import DeliveryState, NoticeKind, NotificationRequest
from boca_socios.notify.projection import list_local_notices
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.notify.telegram_delivery import TelegramDeliveryCoordinator
from boca_socios.notify.telegram_transport import (
    TelegramAck,
    TelegramNotice,
    TelegramTransport,
    TelegramUnconfirmed,
)


class FakeTransport:
    def __init__(self, outcome=None):
        self.outcome = outcome or TelegramAck(42)
        self.notices = []

    async def send(self, notice):
        self.notices.append(notice)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome

    def preflight(self):
        return None


class TelegramDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "boca.sqlite3"
        self.outbox = SqliteNotificationOutbox(self.path)
        self.outbox.migrate()
        self.now = 100.0
        self.request = NotificationRequest(uuid4(), NoticeKind.STATE_CHANGED, {"private": "never"})
        self.outbox.enqueue(self.request, now=self.now)

    def coordinator(self, transport):
        return TelegramDeliveryCoordinator(
            SqliteNotificationOutbox(self.path), transport, lambda: self.now
        )

    def test_ack_is_recorded_without_recipient_or_source_payload(self):
        transport = FakeTransport()
        coordinator = self.coordinator(transport)
        coordinator.prepare_storage()
        report = asyncio.run(coordinator.tick())
        self.assertEqual((report.attempted, report.api_accepted), (1, 1))
        self.assertEqual(
            self.outbox.get(self.request.idempotency_key).state, DeliveryState.ACCEPTED
        )
        notice = list_local_notices(self.outbox.database)[0]
        self.assertEqual((notice.telegram_state, notice.provider_message_id), ("api_accepted", 42))
        self.assertEqual(len(transport.notices), 1)
        self.assertEqual(transport.notices[0].kind, NoticeKind.STATE_CHANGED)
        self.assertNotIn("never", str(notice))
        with self.outbox.database.connection() as connection:
            rows = connection.execute("SELECT * FROM telegram_delivery_attempts").fetchall()
        self.assertNotIn("never", repr(rows))

    def test_timeout_or_exception_stays_ambiguous_and_never_retries(self):
        coordinator = self.coordinator(FakeTransport(TelegramUnconfirmed("private text")))
        coordinator.prepare_storage()
        report = asyncio.run(coordinator.tick())
        self.assertEqual(report.ambiguous, 1)
        self.assertEqual(
            self.outbox.get(self.request.idempotency_key).state, DeliveryState.EXHAUSTED
        )
        self.now = 200.0
        retry = FakeTransport()
        self.assertEqual(asyncio.run(self.coordinator(retry).tick()).attempted, 0)
        self.assertEqual(retry.notices, [])
        self.assertEqual(list_local_notices(self.outbox.database)[0].telegram_state, "ambiguous")

    def test_hard_crash_after_prepared_marker_cannot_send_again(self):
        first = self.coordinator(FakeTransport(SystemExit("simulated process death")))
        first.prepare_storage()
        with self.assertRaises(SystemExit):
            asyncio.run(first.tick())
        self.now = 200.0  # The old lease has expired.
        replacement = FakeTransport()
        self.assertEqual(asyncio.run(self.coordinator(replacement).tick()).attempted, 0)
        self.assertEqual(replacement.notices, [])
        self.assertEqual(list_local_notices(self.outbox.database)[0].telegram_state, "needs_review")

    def test_crash_after_provider_ack_before_settlement_is_never_resent(self):
        coordinator = self.coordinator(FakeTransport())
        coordinator.prepare_storage()
        with patch.object(coordinator, "_settle", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                asyncio.run(coordinator.tick())
        self.now = 200.0
        replacement = FakeTransport()
        self.assertEqual(asyncio.run(self.coordinator(replacement).tick()).attempted, 0)
        self.assertEqual(replacement.notices, [])
        self.assertEqual(list_local_notices(self.outbox.database)[0].telegram_state, "needs_review")

    def test_concurrent_ticks_have_only_one_provider_attempt(self):
        transport = FakeTransport()
        first = self.coordinator(transport)
        first.prepare_storage()

        async def parallel():
            return await asyncio.gather(first.tick(), self.coordinator(transport).tick())

        reports = asyncio.run(parallel())
        self.assertEqual(sum(report.attempted for report in reports), 1)
        self.assertEqual(len(transport.notices), 1)

    def test_no_telegram_migration_or_configuration_is_implicit(self):
        self.assertIsNone(list_local_notices(self.outbox.database)[0].telegram_state)
        with self.assertRaisesRegex(RuntimeError, "Telegram storage is not prepared"):
            asyncio.run(self.coordinator(FakeTransport()).tick())

    def test_read_and_tick_do_not_create_database(self):
        fresh = Path(self.directory.name) / "absent.sqlite3"
        with self.assertRaises(FileNotFoundError):
            list_local_notices(SqliteNotificationOutbox(fresh).database)
        with self.assertRaisesRegex(RuntimeError, "storage is not prepared"):
            asyncio.run(
                TelegramDeliveryCoordinator(
                    SqliteNotificationOutbox(fresh), FakeTransport(), lambda: self.now
                ).tick()
            )
        self.assertFalse(fresh.exists())

    def test_missing_config_does_not_claim_a_notification(self):
        class MissingConfig(FakeTransport):
            def preflight(self):
                raise RuntimeError("private secret")

        coordinator = self.coordinator(MissingConfig())
        coordinator.prepare_storage()
        with self.assertRaisesRegex(RuntimeError, "private configuration unavailable") as failure:
            asyncio.run(coordinator.tick())
        self.assertNotIn("private secret", str(failure.exception))
        self.assertEqual(self.outbox.get(self.request.idempotency_key).state, DeliveryState.PENDING)
        self.assertEqual(list_local_notices(self.outbox.database)[0].telegram_state, None)


class FakeConnection:
    def __init__(self, host, timeout, context):
        self.host, self.timeout, self.context = host, timeout, context
        self.requests = []
        self.status = 200
        self.body = b'{"ok":true,"result":{"message_id":42,"chat":{"id":123}}}'
        self.closed = False

    def request(self, method, path, body, headers):
        self.requests.append((method, path, body, headers))

    def getresponse(self):
        return self

    def read(self, length):
        return self.body[:length]

    def close(self):
        self.closed = True


class TelegramTransportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.token = root / "bot-token"
        self.destination = root / "chat-id"
        self.token.write_text("1:synthetic", encoding="utf-8")
        self.destination.write_text("123", encoding="utf-8")
        self.token.chmod(0o600)
        self.destination.chmod(0o600)
        self.connections = []

    def connection(self, host, timeout, context):
        connection = FakeConnection(host, timeout, context)
        self.connections.append(connection)
        return connection

    def transport(self):
        return TelegramTransport(self.token, self.destination, connection_factory=self.connection)

    def test_fixed_api_host_allowlisted_text_and_provider_ack(self):
        notice = TelegramNotice(uuid4(), NoticeKind.STATE_CHANGED)
        ack = asyncio.run(self.transport().send(notice))
        self.assertEqual(ack.message_id, 42)
        conn = self.connections[0]
        self.assertEqual(conn.host, "api.telegram.org")
        self.assertEqual(conn.timeout, 3.0)
        self.assertTrue(conn.closed)
        method, path, body, headers = conn.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/bot1:synthetic/sendMessage")
        self.assertIn(b'"chat_id":123', body)
        self.assertIn(b"Simulaci", body)
        self.assertNotIn(str(notice.idempotency_key).encode(), body)
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_unverified_response_or_missing_config_never_claims_delivery(self):
        self.destination.unlink()
        with self.assertRaises(TelegramUnconfirmed) as missing:
            asyncio.run(self.transport().send(TelegramNotice(uuid4(), NoticeKind.HEARTBEAT)))
        self.assertEqual(self.connections, [])
        self.assertNotIn(str(self.token), str(missing.exception))
        self.destination.write_text("123", encoding="utf-8")
        self.destination.chmod(0o600)
        conn = self.connection("api.telegram.org", 3.0, None)
        conn.status = 302  # No redirect, especially with token in the request path.
        transport = TelegramTransport(
            self.token, self.destination, connection_factory=lambda **kw: conn
        )
        with self.assertRaises(TelegramUnconfirmed):
            asyncio.run(transport.send(TelegramNotice(uuid4(), NoticeKind.HEARTBEAT)))
        self.assertTrue(conn.closed)


if __name__ == "__main__":
    unittest.main()
