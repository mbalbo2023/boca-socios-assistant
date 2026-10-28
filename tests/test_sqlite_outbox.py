"""Durable outbox invariants; every operation stays on local SQLite."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest

from boca_socios.notify.outbox import (
    DeliveryState,
    IdempotencyConflict,
    InvalidClaim,
    NoticeKind,
    NotificationRequest,
    OutboxCapacityError,
    OutboxPolicy,
)
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox


def store(path: Path, policy: OutboxPolicy | None = None) -> SqliteNotificationOutbox:
    result = SqliteNotificationOutbox(path, policy)
    result.migrate()
    return result


def test_dedupe_and_sanitization_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "boca.sqlite3"
    first = store(path)
    key = uuid4()
    request = NotificationRequest(
        key,
        NoticeKind.STATE_CHANGED,
        untrusted_payload={"password": "never-in-sqlite", "queueittoken": "never-in-sqlite"},
    )
    original = first.enqueue(request, now=1000)
    reopened = store(path)
    assert reopened.enqueue(request, now=1001) == original
    assert reopened.get(key) == original
    with pytest.raises(IdempotencyConflict):
        reopened.enqueue(NotificationRequest(key, NoticeKind.HEARTBEAT), now=1002)

    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT * FROM notification_outbox").fetchall()
        assert len(rows) == 1
        assert "never-in-sqlite" not in repr(rows)
        assert "queueittoken" not in repr(rows)


def test_concurrent_claim_fencing_and_restart_recovery(tmp_path: Path) -> None:
    path = tmp_path / "boca.sqlite3"
    policy = OutboxPolicy(lease_seconds=2, initial_backoff_seconds=1, max_claims_per_window=20)
    first, second = store(path, policy), store(path, policy)
    key = uuid4()
    first.enqueue(NotificationRequest(key, NoticeKind.ACTION_REQUIRED), now=1000)
    barrier = Barrier(2)

    def compete(outbox: SqliteNotificationOutbox) -> tuple:
        barrier.wait()
        return outbox.claim_ready(now=1000, limit=1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(compete, (first, second)))
    assert sorted(len(batch) for batch in claims) == [0, 1]
    stale = next(batch[0] for batch in claims if batch)
    assert stale.attempt_number == 1
    assert first.get(key).state is DeliveryState.CLAIMED  # type: ignore[union-attr]

    restarted = store(path, policy)
    assert restarted.claim_ready(now=1002) == ()  # Lease expires, then backoff.
    new_claim = restarted.claim_ready(now=1003)[0]
    assert new_claim.attempt_number == 2
    assert new_claim.lease_token != stale.lease_token
    with pytest.raises(InvalidClaim):
        first.accept(stale, now=1003)
    accepted = restarted.accept(new_claim, now=1003)
    assert accepted.state is DeliveryState.ACCEPTED
    assert store(path, policy).claim_ready(now=1004) == ()


def test_durable_rate_backpressure_priority_and_retry_after(tmp_path: Path) -> None:
    path = tmp_path / "boca.sqlite3"
    policy = OutboxPolicy(
        max_claims_per_window=1,
        rate_window_seconds=10,
        initial_backoff_seconds=2,
        max_backoff_seconds=5,
    )
    first = store(path, policy)
    low, high = uuid4(), uuid4()
    first.enqueue(NotificationRequest(low, NoticeKind.HEARTBEAT), now=1000)
    first.enqueue(NotificationRequest(high, NoticeKind.ACTION_REQUIRED), now=1000)
    initial = first.claim_ready(now=1000, limit=2)
    assert len(initial) == 1 and initial[0].idempotency_key == high
    first.fail(initial[0], now=1001, retry_after_seconds=20)
    second = store(path, policy)
    assert second.claim_ready(now=1001) == ()
    assert second.claim_ready(now=1010)[0].idempotency_key == low
    assert second.claim_ready(now=1021)[0].idempotency_key == high


def test_ttl_attempt_budget_and_capacity_fail_closed(tmp_path: Path) -> None:
    policy = OutboxPolicy(max_attempts=1, max_records=2, lease_seconds=2)
    box = store(tmp_path / "boca.sqlite3", policy)
    expired, exhausted = uuid4(), uuid4()
    box.enqueue(NotificationRequest(expired, NoticeKind.HEARTBEAT), now=1000, ttl_seconds=1)
    box.enqueue(NotificationRequest(exhausted, NoticeKind.HEARTBEAT), now=1000)
    with pytest.raises(OutboxCapacityError):
        box.enqueue(NotificationRequest(uuid4(), NoticeKind.HEARTBEAT), now=1000)
    claim = box.claim_ready(now=1001)[0]
    assert claim.idempotency_key == exhausted
    assert box.get(expired).state is DeliveryState.EXHAUSTED  # type: ignore[union-attr]
    assert box.fail(claim, now=1001).state is DeliveryState.EXHAUSTED
    assert store(tmp_path / "boca.sqlite3", policy).claim_ready(now=2000) == ()


def test_migration_checksum_guard_and_invalid_inputs(tmp_path: Path) -> None:
    path = tmp_path / "boca.sqlite3"
    box = store(path)
    with pytest.raises(ValueError, match="finite"):
        box.claim_ready(now=float("nan"))
    with pytest.raises(ValueError, match="ttl"):
        box.enqueue(NotificationRequest(uuid4(), NoticeKind.HEARTBEAT), now=1000, ttl_seconds=0)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE schema_migrations SET checksum='tampered' WHERE version=2")
    with pytest.raises(ValueError, match="checksum"):
        store(path)
