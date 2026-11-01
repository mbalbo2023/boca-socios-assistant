"""Synthetic-only dispatcher integration tests against a temporary durable outbox."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from boca_socios.notify.dispatcher import (
    DispatchStopped,
    SyntheticDispatcher,
    SyntheticNotice,
    SyntheticResult,
    SyntheticStatus,
)
from boca_socios.notify.outbox import DeliveryState, NoticeKind, NotificationRequest, OutboxPolicy
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox


class FakeTransport:
    def __init__(self, result=None):
        self.result = result or SyntheticResult(SyntheticStatus.ACCEPTED)
        self.notices = []

    async def send(self, notice):
        self.notices.append(notice)
        await asyncio.sleep(0)
        return self.result


class NotificationDispatcherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "outbox.sqlite3"
        self.policy = OutboxPolicy(max_claims_per_window=100)
        self.outbox = self.reopen()
        self.outbox.migrate()
        self.now = 100.0

    def reopen(self):
        return SqliteNotificationOutbox(self.path, self.policy)

    def enqueue(self):
        request = NotificationRequest(uuid4(), NoticeKind.ACTION_REQUIRED, {"secret": "do-not-copy"})
        self.outbox.enqueue(request, now=self.now)
        return request

    def dispatcher(self, transport, **kwargs):
        return SyntheticDispatcher(self.reopen(), transport, lambda: self.now, **kwargs)

    def state(self, request):
        return self.reopen().get(request.idempotency_key).state

    def test_accepted_dedup_survives_restart_and_drops_source_payload(self):
        request = self.enqueue()
        transport = FakeTransport()
        report = asyncio.run(self.dispatcher(transport).tick())
        self.assertEqual((report.attempted, report.accepted), (1, 1))
        self.outbox.enqueue(request, now=self.now)
        self.assertEqual(asyncio.run(self.dispatcher(transport).tick()).attempted, 0)
        self.assertEqual(len(transport.notices), 1)
        notice = transport.notices[0]
        self.assertIsInstance(notice, SyntheticNotice)
        self.assertEqual(notice.idempotency_key, request.idempotency_key)
        self.assertNotIn("do-not-copy", notice.message)
        self.assertNotIn(str(request.idempotency_key), repr(notice))
        self.assertFalse(hasattr(notice, "lease_token"))
        self.assertEqual(self.state(request), DeliveryState.ACCEPTED)

    def test_budget_leaves_unclaimed_work_for_next_tick(self):
        for _ in range(3):
            self.enqueue()
        transport = FakeTransport()
        dispatcher = self.dispatcher(transport, max_per_tick=2)
        self.assertEqual(asyncio.run(dispatcher.tick()).attempted, 2)
        self.assertEqual(asyncio.run(dispatcher.tick()).attempted, 1)

    def test_retry_after_is_durable_across_restart(self):
        request = self.enqueue()
        retry = FakeTransport(SyntheticResult(SyntheticStatus.RETRYABLE, retry_after_seconds=20))
        report = asyncio.run(self.dispatcher(retry).tick())
        self.assertEqual(report.retryable, 1)
        self.assertEqual(self.state(request), DeliveryState.PENDING)
        self.now = 119
        accepted = FakeTransport()
        self.assertEqual(asyncio.run(self.dispatcher(accepted).tick()).attempted, 0)
        self.now = 120
        self.assertEqual(asyncio.run(self.dispatcher(accepted).tick()).accepted, 1)
        self.assertEqual(self.reopen().get(request.idempotency_key).attempts, 2)

    def test_explicit_permanent_and_ambiguous_are_terminal_after_restart(self):
        for status in (SyntheticStatus.PERMANENT, SyntheticStatus.AMBIGUOUS):
            with self.subTest(status=status):
                request = self.enqueue()
                report = asyncio.run(self.dispatcher(FakeTransport(SyntheticResult(status))).tick())
                self.assertEqual(getattr(report, status.value), 1)
                self.assertEqual(self.state(request), DeliveryState.EXHAUSTED)
                self.now += 100
                self.assertEqual(asyncio.run(self.dispatcher(FakeTransport()).tick()).attempted, 0)

    def test_exception_and_invalid_result_become_redacted_terminal_ambiguity(self):
        class BrokenTransport:
            async def send(self, notice):
                raise RuntimeError("do-not-copy")

        for transport in (BrokenTransport(), FakeTransport("do-not-copy")):
            with self.subTest(transport=type(transport).__name__):
                request = self.enqueue()
                report = asyncio.run(self.dispatcher(transport).tick())
                self.assertEqual(report.ambiguous, 1)
                self.assertNotIn("do-not-copy", repr(report))
                self.assertEqual(self.state(request), DeliveryState.EXHAUSTED)

    def test_timeout_is_terminal_ambiguity(self):
        class SlowTransport:
            async def send(self, notice):
                await asyncio.sleep(1)
                return SyntheticResult(SyntheticStatus.ACCEPTED)

        request = self.enqueue()
        report = asyncio.run(self.dispatcher(SlowTransport(), timeout_seconds=0.01).tick())
        self.assertEqual(report.ambiguous, 1)
        self.assertEqual(self.state(request), DeliveryState.EXHAUSTED)

    def test_cancellation_exhausts_claim_and_propagates(self):
        request = self.enqueue()

        class CancelledTransport:
            async def send(self, notice):
                raise asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(self.dispatcher(CancelledTransport()).tick())
        self.assertEqual(self.state(request), DeliveryState.EXHAUSTED)

    def test_concurrent_workers_do_not_send_same_active_claim(self):
        self.enqueue()
        transport = FakeTransport()

        async def run():
            return await asyncio.gather(
                self.dispatcher(transport).tick(), self.dispatcher(transport).tick()
            )

        reports = asyncio.run(run())
        self.assertEqual(sum(report.accepted for report in reports), 1)
        self.assertEqual(len(transport.notices), 1)

    def test_stale_settlement_cannot_accept_newer_lease_and_stops_tick(self):
        request = self.enqueue()
        case = self
        newer = []

        class LeaseStealingTransport:
            async def send(self, notice):
                case.now = 111
                case.assertEqual(case.reopen().claim_ready(now=case.now), ())
                case.now = 113
                newer.extend(case.reopen().claim_ready(now=case.now))
                return SyntheticResult(SyntheticStatus.ACCEPTED)

        with self.assertRaisesRegex(DispatchStopped, "settlement failed"):
            asyncio.run(self.dispatcher(LeaseStealingTransport()).tick())
        self.assertEqual(len(newer), 1)
        self.assertEqual(self.state(request), DeliveryState.CLAIMED)
        self.reopen().accept(newer[0], now=self.now)
        self.assertEqual(self.state(request), DeliveryState.ACCEPTED)

    def test_crash_without_settlement_remains_retryable_and_is_not_exactly_once(self):
        # Existing schema cannot record unknown transport outcomes across a hard crash.
        request = self.enqueue()
        first = self.outbox.claim_ready(now=self.now)[0]
        self.assertEqual(first.attempt_number, 1)
        self.assertEqual(self.reopen().claim_ready(now=111), ())
        replacement = self.reopen().claim_ready(now=113)[0]
        self.assertEqual(replacement.idempotency_key, request.idempotency_key)
        self.assertEqual(replacement.attempt_number, 2)

    def test_configuration_and_result_validation(self):
        for budget in (0, -1, True, 101, 1.5):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                self.dispatcher(FakeTransport(), max_per_tick=budget)
        for timeout in (0, -1, True, float("nan"), float("inf"), 6):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.dispatcher(FakeTransport(), timeout_seconds=timeout)
        for delay in (-1, True, float("nan"), float("inf")):
            with self.subTest(delay=delay), self.assertRaises(ValueError):
                SyntheticResult(SyntheticStatus.RETRYABLE, delay)
        with self.assertRaises(ValueError):
            SyntheticResult(SyntheticStatus.ACCEPTED, 1)
        with self.assertRaises(ValueError):
            SyntheticResult("accepted")
