"""Offline queue behavior: no external service, authorization or ticket issuance."""

from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta

import pytest

from boca_socios.queue import (
    IdentityPolicy,
    InvalidStateTransition,
    OfflineQueueSimulator,
    PrequeuePolicy,
    QueueState,
    SimulatorConfig,
    check_transition,
)

BASE = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
OPEN = BASE + timedelta(minutes=10)
CLOSE = OPEN + timedelta(minutes=10)


def simulator(
    *,
    policy: PrequeuePolicy = PrequeuePolicy.LOTTERY,
    seed: int = 17,
    opens_at: datetime = OPEN,
    closes_at: datetime = CLOSE,
    max_wait: timedelta | None = None,
    admission_ttl: timedelta = timedelta(minutes=3),
    identity_policy: IdentityPolicy = IdentityPolicy.COALESCE,
) -> OfflineQueueSimulator:
    return OfflineQueueSimulator(
        SimulatorConfig(
            event_id="fixture-event-42",
            opens_at=opens_at,
            closes_at=closes_at,
            max_wait=max_wait,
            admission_ttl=admission_ttl,
            prequeue_policy=policy,
            lottery_seed=seed,
            identity_policy=identity_policy,
        )
    )


def prequeue_members(queue: OfflineQueueSimulator, members: list[str]) -> None:
    for member in members:
        queue.create_session(member, f"session-{member}", BASE)
        assert queue.join(f"session-{member}", BASE).state is QueueState.PREQUEUE


def test_typed_state_graph_rejects_every_terminal_reactivation() -> None:
    check_transition(QueueState.CREATED, QueueState.PREQUEUE)
    check_transition(QueueState.PREQUEUE, QueueState.WAITING)
    check_transition(QueueState.WAITING, QueueState.ADMITTED)
    check_transition(QueueState.ADMITTED, QueueState.EXPIRED)

    for terminal in (
        QueueState.EXPIRED,
        QueueState.CANCELLED,
        QueueState.CLOSED,
        QueueState.ERROR,
    ):
        for next_state in QueueState:
            with pytest.raises(InvalidStateTransition):
                check_transition(terminal, next_state)
    with pytest.raises(InvalidStateTransition):
        check_transition(QueueState.CREATED, QueueState.ADMITTED)


def test_seeded_prequeue_lottery_is_reproducible_and_registration_order_independent() -> None:
    members = [f"opaque-{i:02d}" for i in range(16)]
    first = simulator(seed=123)
    replay = simulator(seed=123)
    other_seed = simulator(seed=456)
    prequeue_members(first, members)
    prequeue_members(replay, list(reversed(members)))
    prequeue_members(other_seed, members)

    assert all(first.snapshot(f"session-{member}").position is None for member in members)
    assert first.waiting_order == ()
    for queue in (first, replay, other_seed):
        queue.advance(OPEN)

    assert first.waiting_order == replay.waiting_order
    assert first.waiting_order != other_seed.waiting_order
    assert set(first.waiting_order) == set(members)
    assert len(first.waiting_order) == len(members)
    assert first.snapshot(f"session-{first.waiting_order[0]}").position == 1
    first.advance(OPEN)  # no second draw at the same instant
    assert first.waiting_order == replay.waiting_order


def test_fifo_prequeue_and_post_open_arrivals_have_stable_order() -> None:
    queue = simulator(policy=PrequeuePolicy.FIFO)
    prequeue_members(queue, ["m3", "m1", "m2"])
    queue.advance(OPEN)
    for member in ("m4", "m5"):
        queue.create_session(member, f"s-{member}", OPEN + timedelta(seconds=1))
        assert queue.join(f"s-{member}", OPEN + timedelta(seconds=1)).position is not None

    assert queue.waiting_order == ("m3", "m1", "m2", "m4", "m5")
    assert [queue.admit_next(OPEN + timedelta(seconds=2)).member_id for _ in range(5)] == [
        "m3",
        "m1",
        "m2",
        "m4",
        "m5",
    ]
    assert queue.admit_next(OPEN + timedelta(seconds=2)) is None
    assert queue.state_counts()[QueueState.ADMITTED] == 5


def test_lottery_only_reorders_prequeue_not_fifo_late_arrivals() -> None:
    queue = simulator(seed=987)
    prequeue_members(queue, ["a", "b", "c"])
    queue.advance(OPEN)
    randomized_prefix = queue.waiting_order
    queue.create_session("late-1", "late-session-1", OPEN + timedelta(seconds=1))
    queue.join("late-session-1", OPEN + timedelta(seconds=1))
    queue.create_session("late-2", "late-session-2", OPEN + timedelta(seconds=2))
    queue.join("late-session-2", OPEN + timedelta(seconds=2))
    assert queue.waiting_order == (*randomized_prefix, "late-1", "late-2")


def test_multiple_logical_sessions_share_one_request_and_one_admission() -> None:
    queue = simulator()
    initial = queue.create_session("opaque-member", "session-a", BASE)
    alias = queue.create_session("opaque-member", "session-b", BASE)
    assert initial.state is QueueState.CREATED
    assert alias.session_ids == ("session-a", "session-b")
    assert alias.requested_quantity == 1
    assert queue.create_session("opaque-member", "session-b", BASE) == alias
    assert queue.request_count == 1
    assert queue.session_count == 2

    assert queue.join("session-a", BASE).state is QueueState.PREQUEUE
    assert queue.join("session-b", BASE).state is QueueState.PREQUEUE
    queue.advance(OPEN)
    assert queue.waiting_order == ("opaque-member",)
    assert queue.snapshot("session-a").position == queue.snapshot("session-b").position == 1
    assert queue.admit_next(OPEN) is not None
    assert queue.admit_next(OPEN) is None
    assert queue.join("session-b", OPEN).state is QueueState.ADMITTED
    assert queue.snapshot("session-a").state is QueueState.ADMITTED
    assert queue.state_counts()[QueueState.ADMITTED] == 1
    assert queue.request_count == 1


def test_duplicate_session_id_for_other_member_is_rejected() -> None:
    queue = simulator()
    queue.create_session("member-a", "unique-session", BASE)
    with pytest.raises(ValueError, match="another member"):
        queue.create_session("member-b", "unique-session", BASE)
    assert queue.request_count == 1
    with pytest.raises(KeyError, match="unknown logical session"):
        queue.snapshot("unknown-session")


def test_configurable_strict_member_identity_rejects_new_session_aliases() -> None:
    queue = simulator(identity_policy=IdentityPolicy.SINGLE_SESSION)
    first = queue.create_session("member", "first", BASE)
    assert queue.create_session("member", "first", BASE) == first
    with pytest.raises(ValueError, match="only one session"):
        queue.create_session("member", "second", BASE)
    assert queue.request_count == 1
    assert queue.session_count == 1
    queue.join("first", BASE)
    queue.advance(OPEN)
    assert queue.waiting_order == ("member",)


def test_thousand_synthetic_sessions_use_only_one_logical_position_per_member() -> None:
    queue = simulator()
    for i in range(1000):
        member = f"member-{i % 100:03d}"
        session = f"synthetic-session-{i:04d}"
        queue.create_session(member, session, BASE)
        queue.join(session, BASE)
    assert queue.session_count == 1000
    assert queue.request_count == 100
    assert queue.state_counts()[QueueState.PREQUEUE] == 100
    queue.advance(OPEN)
    assert len(queue.waiting_order) == 100
    assert len({queue.admit_next(OPEN).member_id for _ in range(100)}) == 100
    assert queue.admit_next(OPEN) is None


def test_cancellation_is_idempotent_and_invalidates_all_session_aliases() -> None:
    queue = simulator()
    queue.create_session("a", "a1", BASE)
    queue.create_session("a", "a2", BASE)
    queue.create_session("b", "b1", BASE)
    queue.join("a1", BASE)
    queue.join("b1", BASE)
    cancelled = queue.cancel("a2", BASE + timedelta(seconds=1))
    assert cancelled.state is QueueState.CANCELLED
    assert queue.cancel("a1", BASE + timedelta(seconds=1)) == cancelled
    assert queue.snapshot("a1") == queue.snapshot("a2")
    queue.advance(OPEN)
    assert queue.waiting_order == ("b",)
    assert queue.admit_next(OPEN).member_id == "b"
    assert queue.admit_next(OPEN) is None
    assert queue.state_counts()[QueueState.CANCELLED] == 1
    with pytest.raises(InvalidStateTransition):
        queue.create_session("a", "a3", OPEN)
    with pytest.raises(InvalidStateTransition):
        queue.join("a1", OPEN)


def test_cancellation_of_admitted_request_does_not_restore_its_queue_position() -> None:
    queue = simulator()
    queue.create_session("member", "one", OPEN)
    queue.create_session("member", "two", OPEN)
    queue.join("one", OPEN)
    assert queue.admit_next(OPEN).state is QueueState.ADMITTED
    assert queue.cancel("two", OPEN + timedelta(seconds=1)).state is QueueState.CANCELLED
    assert queue.snapshot("one").state is QueueState.CANCELLED
    assert queue.admit_next(OPEN + timedelta(seconds=1)) is None
    with pytest.raises(InvalidStateTransition):
        queue.finish("one", OPEN + timedelta(seconds=1))


def test_admission_expires_at_exact_deadline_and_cannot_be_reactivated() -> None:
    queue = simulator(admission_ttl=timedelta(seconds=30))
    queue.create_session("member", "s1", OPEN)
    queue.join("s1", OPEN)
    admitted = queue.admit_next(OPEN)
    assert admitted.state is QueueState.ADMITTED
    assert admitted.deadline_at == OPEN + timedelta(seconds=30)
    queue.advance(OPEN + timedelta(seconds=29))
    assert queue.snapshot("s1").state is QueueState.ADMITTED
    queue.advance(OPEN + timedelta(seconds=30))
    expired = queue.snapshot("s1")
    assert expired.state is QueueState.EXPIRED
    assert expired.ended_at == OPEN + timedelta(seconds=30)
    with pytest.raises(InvalidStateTransition):
        queue.join("s1", OPEN + timedelta(seconds=30))
    with pytest.raises(InvalidStateTransition):
        queue.cancel("s1", OPEN + timedelta(seconds=30))


def test_wait_deadline_starts_at_open_for_prequeue_and_join_for_late_entry() -> None:
    queue = simulator(max_wait=timedelta(minutes=2))
    queue.create_session("pre", "p", BASE)
    queue.join("p", BASE)
    queue.advance(OPEN)
    assert queue.snapshot("p").deadline_at == OPEN + timedelta(minutes=2)
    queue.create_session("late", "l", OPEN + timedelta(minutes=1))
    queue.join("l", OPEN + timedelta(minutes=1))
    assert queue.snapshot("l").deadline_at == OPEN + timedelta(minutes=3)

    queue.advance(OPEN + timedelta(minutes=2))
    assert queue.snapshot("p").state is QueueState.EXPIRED
    assert queue.snapshot("l").state is QueueState.WAITING
    assert queue.waiting_order == ("late",)
    queue.advance(OPEN + timedelta(minutes=3))
    assert queue.snapshot("l").state is QueueState.EXPIRED
    assert queue.waiting_order == ()


def test_event_close_precedes_later_wait_expiry_even_in_large_time_jump() -> None:
    queue = simulator(max_wait=timedelta(hours=1))
    queue.create_session("joined", "j", BASE)
    queue.create_session("never-joined", "n", BASE)
    queue.join("j", BASE)
    queue.advance(CLOSE + timedelta(hours=2))
    assert queue.snapshot("j").state is QueueState.CLOSED
    assert queue.snapshot("j").ended_at == CLOSE
    assert queue.snapshot("n").state is QueueState.CLOSED
    assert queue.waiting_order == ()
    assert queue.admit_next(CLOSE + timedelta(hours=2)) is None


def test_admitted_deadline_survives_event_close_but_not_its_own_ttl() -> None:
    queue = simulator(admission_ttl=timedelta(minutes=20))
    queue.create_session("member", "s", CLOSE - timedelta(seconds=1))
    queue.join("s", CLOSE - timedelta(seconds=1))
    queue.admit_next(CLOSE - timedelta(seconds=1))
    queue.advance(CLOSE)
    assert queue.snapshot("s").state is QueueState.ADMITTED
    queue.advance(CLOSE + timedelta(minutes=20))
    assert queue.snapshot("s").state is QueueState.EXPIRED


def test_finish_is_only_for_admitted_state_and_does_not_reserve_a_ticket() -> None:
    queue = simulator()
    queue.create_session("member", "s", OPEN)
    queue.join("s", OPEN)
    with pytest.raises(InvalidStateTransition):
        queue.finish("s", OPEN)
    queue.admit_next(OPEN)
    finished = queue.finish("s", OPEN + timedelta(seconds=1))
    assert finished.state is QueueState.CLOSED
    assert finished.ended_at == OPEN + timedelta(seconds=1)
    assert finished.requested_quantity == 1
    assert queue.admit_next(OPEN + timedelta(seconds=1)) is None
    with pytest.raises(InvalidStateTransition):
        queue.finish("s", OPEN + timedelta(seconds=1))


def test_explicit_error_is_terminal_and_removes_pending_request() -> None:
    queue = simulator()
    queue.create_session("member", "s", OPEN)
    queue.join("s", OPEN)
    assert queue.fail("s", OPEN + timedelta(seconds=1)).state is QueueState.ERROR
    assert queue.waiting_order == ()
    with pytest.raises(InvalidStateTransition):
        queue.join("s", OPEN + timedelta(seconds=2))


def test_validation_rejects_incoherent_deadlines_naive_times_and_clock_reversal() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        simulator(opens_at=OPEN.replace(tzinfo=None))
    with pytest.raises(ValueError, match="precede"):
        simulator(closes_at=OPEN)
    with pytest.raises(ValueError, match="positive"):
        simulator(max_wait=timedelta(0))
    with pytest.raises(ValueError, match="positive"):
        simulator(admission_ttl=timedelta(seconds=-1))
    with pytest.raises(ValueError, match="event_id"):
        SimulatorConfig(event_id=" ", opens_at=OPEN, closes_at=CLOSE)
    with pytest.raises(ValueError, match="lottery_seed"):
        SimulatorConfig(event_id="e", opens_at=OPEN, closes_at=CLOSE, lottery_seed=True)
    with pytest.raises(ValueError, match="identity_policy"):
        SimulatorConfig(event_id="e", opens_at=OPEN, closes_at=CLOSE, identity_policy="invalid")

    queue = simulator()
    queue.advance(OPEN)
    with pytest.raises(ValueError, match="backwards"):
        queue.advance(BASE)
    with pytest.raises(ValueError, match="timezone-aware"):
        queue.advance(CLOSE.replace(tzinfo=None))
    with pytest.raises(ValueError, match="nonblank"):
        queue.create_session("", "session", OPEN)


def test_offline_simulation_never_attempts_a_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked_socket(*args: object, **kwargs: object) -> None:
        pytest.fail("simulator attempted forbidden network I/O")

    monkeypatch.setattr(socket, "socket", blocked_socket)
    queue = simulator()
    prequeue_members(queue, ["m1", "m2", "m3"])
    queue.advance(OPEN)
    queue.admit_next(OPEN)
    queue.cancel("session-m3", OPEN + timedelta(seconds=1))
    queue.advance(CLOSE)
    assert queue.request_count == 3
    assert queue.session_count == 3
