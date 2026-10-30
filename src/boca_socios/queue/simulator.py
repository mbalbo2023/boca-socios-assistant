"""An entirely in-memory, clock-injected Queue-it-*like* test simulator.

No URLs, HTTP clients, browser drivers, credentials, cookies, queue passes or
live adapter hooks exist here. The simulator is scoped to ONE event and uses
ONE logical request per member, regardless of local session count.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Literal

from boca_socios.domain.policy import TicketIntent
from boca_socios.queue.state_machine import (
    IdentityPolicy,
    InvalidStateTransition,
    PrequeuePolicy,
    QueueState,
    check_transition,
)


def _check_aware(instant: datetime) -> None:
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("simulator times must be timezone-aware")


@dataclass(frozen=True, slots=True)
class SimulatorConfig:
    """Synthetic opening/closing deadlines and queue-ordering policy.

    max_wait is measured from the moment the entry begins WAITING (at opening
    for a prequeue entrant); admission_ttl begins at synthetic admission.
    An admission may outlive closes_at, but never its own TTL.
    """

    event_id: str
    opens_at: datetime
    closes_at: datetime
    admission_ttl: timedelta = timedelta(minutes=5)
    max_wait: timedelta | None = None
    prequeue_policy: PrequeuePolicy = PrequeuePolicy.LOTTERY
    lottery_seed: int = 0
    identity_policy: IdentityPolicy = IdentityPolicy.COALESCE

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id is required")
        _check_aware(self.opens_at)
        _check_aware(self.closes_at)
        if self.opens_at >= self.closes_at:
            raise ValueError("opens_at must precede closes_at")
        if self.admission_ttl <= timedelta(0):
            raise ValueError("admission_ttl must be positive")
        if self.max_wait is not None and self.max_wait <= timedelta(0):
            raise ValueError("max_wait must be positive when specified")
        if not isinstance(self.prequeue_policy, PrequeuePolicy):
            raise ValueError("prequeue_policy must be a PrequeuePolicy")
        if not isinstance(self.lottery_seed, int) or isinstance(self.lottery_seed, bool):
            raise ValueError("lottery_seed must be an integer")
        if not isinstance(self.identity_policy, IdentityPolicy):
            raise ValueError("identity_policy must be an IdentityPolicy")


@dataclass(frozen=True, slots=True)
class QueueSnapshot:
    """Immutable observation, not a live admission token or reservation."""

    event_id: str
    member_id: str
    session_ids: tuple[str, ...]
    state: QueueState
    position: int | None
    created_at: datetime
    joined_at: datetime | None
    waiting_at: datetime | None
    admitted_at: datetime | None
    deadline_at: datetime | None
    ended_at: datetime | None
    requested_quantity: Literal[1] = 1


@dataclass(slots=True)
class _Entry:
    member_id: str
    created_at: datetime
    state: QueueState = QueueState.CREATED
    session_ids: set[str] = field(default_factory=set)
    joined_at: datetime | None = None
    waiting_at: datetime | None = None
    admitted_at: datetime | None = None
    deadline_at: datetime | None = None
    ended_at: datetime | None = None

    def transition(self, next_state: QueueState) -> None:
        check_transition(self.state, next_state)
        self.state = next_state


class OfflineQueueSimulator:
    """Single-event deterministic queue with an explicit caller-supplied clock.

    - create_session registers local *views*, deduplicated by member/event.
    - join enters prequeue before opens_at or the FIFO line after opens_at.
    - advance opens the prequeue, expires deadlines and closes unserved entries.
    - admit_next grants only a simulated admission, never a ticket reservation.
    - cancel / finish / fail are terminal for every session of the member.

    Calls must use nondecreasing aware timestamps. Replaying the same input
    calls and seed yields the same state and order without outside I/O.
    """

    def __init__(self, config: SimulatorConfig) -> None:
        self.config = config
        self._entries: dict[str, _Entry] = {}
        self._sessions: dict[str, str] = {}
        self._prequeue: list[str] = []
        self._waiting: list[str] = []
        self._opened = False
        self._now: datetime | None = None

    @property
    def request_count(self) -> int:
        """Number of distinct member/event ticket requests, NOT session count."""
        return len(self._entries)

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    @property
    def waiting_order(self) -> tuple[str, ...]:
        """Opaque member IDs in the actual *simulated* admission order."""
        return tuple(self._waiting)

    def state_counts(self) -> dict[QueueState, int]:
        """Counts unique requests, not their possibly many session aliases."""
        counts = {state: 0 for state in QueueState}
        for entry in self._entries.values():
            counts[entry.state] += 1
        return counts

    def create_session(self, member_id: str, session_id: str, at: datetime) -> QueueSnapshot:
        """Create or attach a local session to the member's one logical entry.

        Reusing the same session_id for the same member is idempotent. A
        session ID cannot be reassigned to another member. New sessions
        cannot resurrect a cancelled/expired/closed/failed request.
        """
        if not member_id.strip() or not session_id.strip():
            raise ValueError("member_id and session_id must be nonblank")
        TicketIntent(member_id=member_id, event_id=self.config.event_id).validate()
        # Reject a reassigned alias before advancing the global synthetic
        # clock: a malformed request must not expire other members' entries.
        bound_member = self._sessions.get(session_id)
        if bound_member is not None and bound_member != member_id:
            raise ValueError("session_id already belongs to another member")
        self.advance(at)

        if bound_member is not None:
            return self.snapshot(session_id)

        if at >= self.config.closes_at:
            raise InvalidStateTransition("cannot create a session after event closure")
        entry = self._entries.get(member_id)
        if entry is None:
            entry = _Entry(member_id=member_id, created_at=at)
            self._entries[member_id] = entry
        elif entry.state in {
            QueueState.EXPIRED,
            QueueState.CANCELLED,
            QueueState.CLOSED,
            QueueState.ERROR,
        }:
            raise InvalidStateTransition("cannot attach to a terminal request")
        elif self.config.identity_policy is IdentityPolicy.SINGLE_SESSION:
            raise ValueError("identity policy permits only one session per member/event")

        entry.session_ids.add(session_id)
        self._sessions[session_id] = member_id
        return self.snapshot(session_id)

    def join(self, session_id: str, at: datetime) -> QueueSnapshot:
        """Request one queue position, shared across every logical session."""
        entry = self._entry_for(session_id)
        self.advance(at)
        if entry.state is QueueState.CREATED:
            entry.joined_at = at
            if at < self.config.opens_at:
                entry.transition(QueueState.PREQUEUE)
                self._prequeue.append(entry.member_id)
            else:
                entry.transition(QueueState.WAITING)
                entry.waiting_at = at
                self._set_wait_deadline(entry)
                self._waiting.append(entry.member_id)
        elif entry.state not in {QueueState.PREQUEUE, QueueState.WAITING, QueueState.ADMITTED}:
            raise InvalidStateTransition("cannot rejoin a terminal request")
        return self.snapshot(session_id)

    def advance(self, at: datetime) -> None:
        """Advance simulation time; catch up deterministically even in one jump.

        Waiting expiry wins over event closure only if its deadline is at
        or before closes_at. An admitted entry has its independent TTL.
        """
        _check_aware(at)
        if self._now is not None and at < self._now:
            raise ValueError("simulation time cannot move backwards")

        if not self._opened and at >= self.config.opens_at:
            prequeue = self._ordered_prequeue()
            for member_id in prequeue:
                entry = self._entries[member_id]
                entry.transition(QueueState.WAITING)
                entry.waiting_at = self.config.opens_at
                self._set_wait_deadline(entry)
            self._waiting.extend(prequeue)
            self._prequeue.clear()
            self._opened = True

        for entry in self._entries.values():
            if entry.state is QueueState.ADMITTED:
                if entry.deadline_at is not None and at >= entry.deadline_at:
                    entry.transition(QueueState.EXPIRED)
                    entry.ended_at = entry.deadline_at
            elif entry.state is QueueState.WAITING:
                expiry = entry.deadline_at
                if expiry is not None and at >= expiry and expiry <= self.config.closes_at:
                    entry.transition(QueueState.EXPIRED)
                    entry.ended_at = expiry
                elif at >= self.config.closes_at:
                    entry.transition(QueueState.CLOSED)
                    entry.ended_at = self.config.closes_at
            elif at >= self.config.closes_at and entry.state in {
                QueueState.CREATED,
                QueueState.PREQUEUE,
            }:
                entry.transition(QueueState.CLOSED)
                entry.ended_at = self.config.closes_at

        self._waiting = [
            member_id
            for member_id in self._waiting
            if self._entries[member_id].state is QueueState.WAITING
        ]
        self._now = at

    def admit_next(self, at: datetime) -> QueueSnapshot | None:
        """Simulate admission of the next unique waiting request, if open."""
        self.advance(at)
        if at < self.config.opens_at or at >= self.config.closes_at or not self._waiting:
            return None
        member_id = self._waiting.pop(0)
        entry = self._entries[member_id]
        entry.transition(QueueState.ADMITTED)
        entry.admitted_at = at
        entry.deadline_at = at + self.config.admission_ttl
        return self._snapshot(entry)

    def cancel(self, session_id: str, at: datetime) -> QueueSnapshot:
        """Cancel the single request for all of a member's local sessions."""
        entry = self._entry_for(session_id)
        self.advance(at)
        if entry.state is not QueueState.CANCELLED:
            entry.transition(QueueState.CANCELLED)
            entry.ended_at = at
            self._remove_from_lines(entry.member_id)
        return self.snapshot(session_id)

    def finish(self, session_id: str, at: datetime) -> QueueSnapshot:
        """End an admitted synthetic session; does NOT reserve a ticket."""
        entry = self._entry_for(session_id)
        self.advance(at)
        if entry.state is not QueueState.ADMITTED:
            raise InvalidStateTransition("only an admitted entry can be finished")
        entry.transition(QueueState.CLOSED)
        entry.ended_at = at
        return self.snapshot(session_id)

    def fail(self, session_id: str, at: datetime) -> QueueSnapshot:
        """Record a terminal simulated error without an unsafe retry."""
        entry = self._entry_for(session_id)
        self.advance(at)
        entry.transition(QueueState.ERROR)
        entry.ended_at = at
        self._remove_from_lines(entry.member_id)
        return self.snapshot(session_id)

    def snapshot(self, session_id: str) -> QueueSnapshot:
        """Read state at the last explicit time; this does not advance clocks."""
        return self._snapshot(self._entry_for(session_id))

    def _entry_for(self, session_id: str) -> _Entry:
        try:
            return self._entries[self._sessions[session_id]]
        except KeyError as exc:
            raise KeyError("unknown logical session") from exc

    def _snapshot(self, entry: _Entry) -> QueueSnapshot:
        position = (
            self._waiting.index(entry.member_id) + 1 if entry.state is QueueState.WAITING else None
        )
        return QueueSnapshot(
            event_id=self.config.event_id,
            member_id=entry.member_id,
            session_ids=tuple(sorted(entry.session_ids)),
            state=entry.state,
            position=position,
            created_at=entry.created_at,
            joined_at=entry.joined_at,
            waiting_at=entry.waiting_at,
            admitted_at=entry.admitted_at,
            deadline_at=entry.deadline_at,
            ended_at=entry.ended_at,
        )

    def _ordered_prequeue(self) -> list[str]:
        if self.config.prequeue_policy is PrequeuePolicy.FIFO:
            return self._prequeue.copy()

        # Stable SHA-256 ranking instead of process-global RNG state. A seed
        # gives the same order even if sessions register in a different order.
        def lottery_key(member_id: str) -> bytes:
            identity = f"{self.config.event_id}\0{member_id}".encode()
            payload = f"{self.config.lottery_seed}:".encode("ascii") + identity
            return sha256(payload).digest()

        return sorted(self._prequeue, key=lambda member_id: (lottery_key(member_id), member_id))

    def _set_wait_deadline(self, entry: _Entry) -> None:
        if self.config.max_wait is not None and entry.waiting_at is not None:
            entry.deadline_at = entry.waiting_at + self.config.max_wait

    def _remove_from_lines(self, member_id: str) -> None:
        if member_id in self._prequeue:
            self._prequeue.remove(member_id)
        if member_id in self._waiting:
            self._waiting.remove(member_id)
