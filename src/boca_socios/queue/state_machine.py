"""The explicit state graph for a *logical* simulated queue request.

Multiple local session IDs observe the same request; they do not create
additional queue positions, passes, or permission to purchase tickets.
"""

from __future__ import annotations

from enum import StrEnum


class QueueState(StrEnum):
    CREATED = "created"
    PREQUEUE = "prequeue"
    WAITING = "waiting"
    ADMITTED = "admitted"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    CLOSED = "closed"
    ERROR = "error"


class PrequeuePolicy(StrEnum):
    """How entries already waiting *before* opening are ordered at opening.

    Entries that join after opening always append in FIFO order, regardless
    of this setting. These are synthetic policies, not Boca observations.
    """

    LOTTERY = "lottery"
    FIFO = "fifo"


class IdentityPolicy(StrEnum):
    """Conservative local handling of multiple sessions for one member/event.

    Neither mode grants independent positions to the same member. A future
    experiment about real provider identity rules needs separate approval.
    """

    COALESCE = "coalesce"
    SINGLE_SESSION = "single_session"


class InvalidStateTransition(ValueError):
    """The requested transition would bypass or reactivate a terminal state."""


_ALLOWED: dict[QueueState, frozenset[QueueState]] = {
    QueueState.CREATED: frozenset(
        {
            QueueState.PREQUEUE,
            QueueState.WAITING,
            QueueState.CANCELLED,
            QueueState.CLOSED,
            QueueState.ERROR,
        }
    ),
    QueueState.PREQUEUE: frozenset(
        {QueueState.WAITING, QueueState.CANCELLED, QueueState.CLOSED, QueueState.ERROR}
    ),
    QueueState.WAITING: frozenset(
        {
            QueueState.ADMITTED,
            QueueState.EXPIRED,
            QueueState.CANCELLED,
            QueueState.CLOSED,
            QueueState.ERROR,
        }
    ),
    QueueState.ADMITTED: frozenset(
        {QueueState.EXPIRED, QueueState.CANCELLED, QueueState.CLOSED, QueueState.ERROR}
    ),
    QueueState.EXPIRED: frozenset(),
    QueueState.CANCELLED: frozenset(),
    QueueState.CLOSED: frozenset(),
    QueueState.ERROR: frozenset(),
}


def check_transition(previous: QueueState, following: QueueState) -> None:
    """Reject every edge not explicitly present in the state graph."""
    if following not in _ALLOWED[previous]:
        raise InvalidStateTransition(
            f"cannot transition from {previous.value} to {following.value}"
        )
