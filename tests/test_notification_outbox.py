"""Offline contract tests; no network, Telegram credentials, or real session state."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest

from boca_socios.notify import (
    DeliveryState,
    IdempotencyConflict,
    InvalidClaim,
    NoticeKind,
    NotificationOutbox,
    NotificationRequest,
    OutboxCapacityError,
    OutboxPolicy,
    Priority,
)


def key(number: int) -> UUID:
    return UUID(int=number)


def request(number: int, kind: NoticeKind) -> NotificationRequest:
    return NotificationRequest(idempotency_key=key(number), kind=kind)


def test_priority_and_fifo_are_deterministic() -> None:
    box = NotificationOutbox(OutboxPolicy(max_claims_per_window=8))
    box.enqueue(request(1, NoticeKind.HEARTBEAT), now=0)
    box.enqueue(request(2, NoticeKind.STATE_CHANGED), now=0)
    box.enqueue(request(3, NoticeKind.ACTION_REQUIRED), now=0)
    box.enqueue(request(4, NoticeKind.QUEUE_ADMITTED), now=0)
    box.enqueue(request(5, NoticeKind.ACTION_REQUIRED), now=0)

    claims = box.claim_ready(now=0)
    assert [claim.idempotency_key for claim in claims] == [
        key(3),
        key(5),
        key(4),
        key(2),
        key(1),
    ]
    assert [claim.priority for claim in claims] == [
        Priority.CRITICAL,
        Priority.CRITICAL,
        Priority.HIGH,
        Priority.NORMAL,
        Priority.LOW,
    ]
    assert all("Simulación" in claim.message for claim in claims)
    assert all("http" not in claim.message for claim in claims)


def test_duplicate_key_is_idempotent_even_after_acceptance() -> None:
    box = NotificationOutbox()
    first = box.enqueue(request(7, NoticeKind.ACTION_REQUIRED), now=0)
    again = box.enqueue(request(7, NoticeKind.ACTION_REQUIRED), now=0)
    assert first == again
    assert len(box.records()) == 1

    (claim,) = box.claim_ready(now=0)
    accepted = box.accept(claim, now=1)
    assert accepted.state is DeliveryState.ACCEPTED
    assert accepted.attempts == 1
    assert accepted.acceptance_latency_seconds == 1
    assert box.enqueue(request(7, NoticeKind.ACTION_REQUIRED), now=1) == accepted
    assert box.claim_ready(now=1) == ()

    with pytest.raises(IdempotencyConflict, match="different kind"):
        box.enqueue(request(7, NoticeKind.HEARTBEAT), now=1)


def test_rate_limit_uses_rolling_window_across_calls() -> None:
    box = NotificationOutbox(
        OutboxPolicy(max_claims_per_window=2, rate_window_seconds=10, max_attempts=1)
    )
    for number in range(1, 5):
        box.enqueue(request(number, NoticeKind.STATE_CHANGED), now=0)

    first_batch = box.claim_ready(now=0, limit=3)
    assert len(first_batch) == 2
    assert box.claim_ready(now=9.999) == ()
    second_batch = box.claim_ready(now=10)
    assert len(second_batch) == 2
    assert set(claim.idempotency_key for claim in (*first_batch, *second_batch)) == {
        key(1),
        key(2),
        key(3),
        key(4),
    }


def test_exponential_backoff_is_capped_and_attempts_are_bounded() -> None:
    box = NotificationOutbox(
        OutboxPolicy(
            max_attempts=4,
            initial_backoff_seconds=2,
            max_backoff_seconds=5,
            max_claims_per_window=10,
        )
    )
    box.enqueue(request(1, NoticeKind.ACTION_REQUIRED), now=0)
    expected_attempts = [(0, 2), (2, 6), (6, 11)]
    for attempt_number, (now, ready_again_at) in enumerate(expected_attempts, start=1):
        (claim,) = box.claim_ready(now=now)
        assert claim.attempt_number == attempt_number
        snapshot = box.fail(claim, now=now)
        assert snapshot.state is DeliveryState.PENDING
        assert snapshot.next_attempt_at == ready_again_at
        assert box.claim_ready(now=ready_again_at - 0.01) == ()

    (last_claim,) = box.claim_ready(now=11)
    assert last_claim.attempt_number == 4
    snapshot = box.fail(last_claim, now=11)
    assert snapshot.state is DeliveryState.EXHAUSTED
    assert snapshot.next_attempt_at is None
    assert box.claim_ready(now=10000) == ()


def test_retry_after_is_honored_even_above_local_backoff_cap() -> None:
    box = NotificationOutbox(OutboxPolicy(max_claims_per_window=5, max_backoff_seconds=4))
    box.enqueue(request(1, NoticeKind.QUEUE_ADMITTED), now=0)
    (claim,) = box.claim_ready(now=0)
    snapshot = box.fail(claim, now=0, retry_after_seconds=37)
    assert snapshot.next_attempt_at == 37
    assert box.claim_ready(now=36.99) == ()
    (retry,) = box.claim_ready(now=37)
    assert retry.attempt_number == 2


def test_non_retryable_failure_and_expired_claim_are_fail_closed() -> None:
    box = NotificationOutbox(OutboxPolicy(lease_seconds=5, max_claims_per_window=5))
    box.enqueue(request(1, NoticeKind.ACTION_REQUIRED), now=0)
    (stale_claim,) = box.claim_ready(now=0)

    # An unacknowledged dispatch lease expires; no indefinite in-flight state.
    assert box.claim_ready(now=5) == ()
    entry = box.get(key(1))
    assert entry is not None
    assert entry.state is DeliveryState.PENDING
    assert entry.attempts == 1
    assert entry.next_attempt_at == 7
    with pytest.raises(InvalidClaim):
        box.accept(stale_claim, now=5)

    (valid_claim,) = box.claim_ready(now=7)
    exhausted = box.fail(valid_claim, now=7, retryable=False)
    assert exhausted.state is DeliveryState.EXHAUSTED
    assert exhausted.attempts == 2
    assert box.claim_ready(now=100) == ()


def test_expired_lease_rejects_late_accept_without_another_claim_poll() -> None:
    box = NotificationOutbox(OutboxPolicy(lease_seconds=2))
    box.enqueue(request(1, NoticeKind.QUEUE_ADMITTED), now=0)
    (claim,) = box.claim_ready(now=0)
    with pytest.raises(InvalidClaim):
        box.accept(claim, now=2)
    with pytest.raises(InvalidClaim):
        box.fail(claim, now=3)
    # A later poll applies the lazy expiry and schedules a bounded retry.
    assert box.claim_ready(now=3) == ()
    entry = box.get(key(1))
    assert entry is not None
    assert entry.state is DeliveryState.PENDING
    assert entry.next_attempt_at == 5


def test_extreme_retry_count_cannot_overflow_exponential_backoff() -> None:
    box = NotificationOutbox(
        OutboxPolicy(
            max_attempts=2000,
            initial_backoff_seconds=1e-100,
            max_backoff_seconds=1e100,
            max_claims_per_window=2000,
            rate_window_seconds=1e-150,
            # The synthetic clock grows to enormous values; keep a lease
            # larger than any such timestamp to isolate backoff arithmetic.
            lease_seconds=1e200,
        )
    )
    box.enqueue(request(1, NoticeKind.HEARTBEAT), now=0)
    now = 0.0
    for _ in range(750):
        (claim,) = box.claim_ready(now=now)
        entry = box.fail(claim, now=now)
        assert entry.next_attempt_at is not None
        now = entry.next_attempt_at
    assert box.get(key(1)) is not None


def test_untrusted_payload_is_discarded_and_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    # Synthetic sentinels, not credentials or real session URLs.
    sentinels = (
        "SYNTHETIC_PASSWORD_MARKER",
        "SYNTHETIC_COOKIE_MARKER",
        "https://localhost.invalid/mock-session?pass=SYNTHETIC_PASS_MARKER",
    )
    untrusted = {
        "password": sentinels[0],
        "cookies": {"session": sentinels[1]},
        "queue_link": sentinels[2],
        "free_text": "Never render this value",
    }
    box = NotificationOutbox()
    payload = NotificationRequest(
        idempotency_key=key(1),
        kind=NoticeKind.ACTION_REQUIRED,
        untrusted_payload=untrusted,
    )
    stored = box.enqueue(payload, now=0)
    (claim,) = box.claim_ready(now=0)
    box.accept(claim, now=1)
    representations = (
        repr(payload),
        repr(stored),
        repr(box.records()),
        repr(claim),
        repr(box.acceptance_metrics()),
        caplog.text,
    )
    assert all(sentinel not in output for output in representations for sentinel in sentinels)
    assert all("Never render" not in output for output in representations)
    assert claim.message == "Simulación: revisión manual pendiente. No se realizó ninguna compra."
    assert not caplog.records


def test_simulated_transport_failure_does_not_store_exception_or_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    box = NotificationOutbox()
    box.enqueue(request(1, NoticeKind.STATE_CHANGED), now=0)
    (claim,) = box.claim_ready(now=0)
    try:
        raise RuntimeError("synthetic-sensitive-error-detail")
    except RuntimeError:
        # Only a retryable outcome crosses the outbox boundary, never exception text.
        pending = box.fail(claim, now=0, retryable=True)
    assert pending.state is DeliveryState.PENDING
    assert "synthetic-sensitive-error-detail" not in repr(pending)
    assert "synthetic-sensitive-error-detail" not in repr(box.records())
    assert not caplog.records


def test_dry_run_has_no_transport_and_reports_only_simulated_latency() -> None:
    box = NotificationOutbox(OutboxPolicy(max_claims_per_window=3))
    box.enqueue(request(1, NoticeKind.STATE_CHANGED), now=0)
    box.enqueue(request(2, NoticeKind.ACTION_REQUIRED), now=2)
    claims = box.run_dry_run(now=5)
    assert len(claims) == 2
    assert all(item.state is DeliveryState.ACCEPTED for item in box.records())
    stats = box.acceptance_metrics()
    assert stats.accepted_count == 2
    assert stats.p95_seconds == 5
    assert stats.p99_seconds == 5
    assert box.run_dry_run(now=6) == ()


def test_concurrent_claims_never_duplicate_an_attempt() -> None:
    box = NotificationOutbox(OutboxPolicy(max_claims_per_window=20))
    for number in range(1, 11):
        box.enqueue(request(number, NoticeKind.STATE_CHANGED), now=0)
    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = tuple(pool.map(lambda _: box.claim_ready(now=0, limit=10), range(4)))
    claims = tuple(claim for batch in batches for claim in batch)
    assert len(claims) == 10
    assert len({claim.idempotency_key for claim in claims}) == 10


def test_capacity_invalid_inputs_and_stale_claim_are_rejected_safely() -> None:
    with pytest.raises(ValueError):
        OutboxPolicy(max_attempts=0)
    with pytest.raises(ValueError):
        OutboxPolicy(max_claims_per_window=0)
    with pytest.raises(ValueError):
        OutboxPolicy(initial_backoff_seconds=float("inf"))

    box = NotificationOutbox(OutboxPolicy(max_records=1))
    box.enqueue(request(1, NoticeKind.HEARTBEAT), now=0)
    with pytest.raises(OutboxCapacityError):
        box.enqueue(request(2, NoticeKind.HEARTBEAT), now=0)
    with pytest.raises(ValueError):
        box.claim_ready(now=float("nan"))
    with pytest.raises(ValueError):
        box.claim_ready(now=0, limit=0)
    (claim,) = box.claim_ready(now=0)
    box.accept(claim, now=1)
    with pytest.raises(InvalidClaim):
        box.accept(claim, now=1)
    with pytest.raises(ValueError):
        box.enqueue(request(1, NoticeKind.HEARTBEAT), now=0.5)
