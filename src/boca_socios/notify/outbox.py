"""Bounded in-memory notification outbox with no external I/O.

Only a fixed, allowlisted Spanish template may become an outbound message.
Untrusted upstream payloads are deliberately discarded, not redacted with a
fallible blacklist. An owner-approved Telegram transport and durable store are
both future work; ``run_dry_run`` only acknowledges messages in this process.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from math import ceil, isfinite, ldexp, log2
from threading import RLock
from uuid import UUID


class Priority(IntEnum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class NoticeKind(StrEnum):
    """Finite set of synthetic events; arbitrary content is never rendered."""

    ACTION_REQUIRED = "action_required"
    QUEUE_ADMITTED = "queue_admitted"
    STATE_CHANGED = "state_changed"
    HEARTBEAT = "heartbeat"


_SAFE_NOTICE: Mapping[NoticeKind, tuple[Priority, str]] = {
    NoticeKind.ACTION_REQUIRED: (
        Priority.CRITICAL,
        "Simulación: revisión manual pendiente. No se realizó ninguna compra.",
    ),
    NoticeKind.QUEUE_ADMITTED: (
        Priority.HIGH,
        "Simulación: admisión sintética a la cola; verificar manualmente. No confirma una entrada.",
    ),
    NoticeKind.STATE_CHANGED: (
        Priority.NORMAL,
        "Simulación: cambió el estado interno del seguimiento.",
    ),
    NoticeKind.HEARTBEAT: (
        Priority.LOW,
        "Simulación: seguimiento sintético activo.",
    ),
}


class DeliveryState(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    ACCEPTED = "accepted"
    EXHAUSTED = "exhausted"


class IdempotencyConflict(ValueError):
    """A stable key was reused for a different event kind."""


class InvalidClaim(ValueError):
    """A claim is stale, already settled, or does not belong to the outbox."""


class OutboxCapacityError(RuntimeError):
    """The local store's explicit record budget has been reached."""


@dataclass(frozen=True, slots=True, repr=False)
class NotificationRequest:
    """One logical notification, identified by a caller-stable opaque UUID.

    ``untrusted_payload`` accommodates source event context but is NEVER
    inspected, serialized, logged, copied into a record or displayed. Callers
    should avoid passing secrets at all; this discarding boundary protects
    against accidental inclusion of future upstream metadata.
    """

    idempotency_key: UUID
    kind: NoticeKind
    untrusted_payload: Mapping[str, object] | None = field(default=None, compare=False)

    def __repr__(self) -> str:
        return "NotificationRequest(<untrusted payload omitted>)"


@dataclass(frozen=True, slots=True)
class OutboxPolicy:
    """Rate, capacity, attempt and lease budgets for one in-process outbox."""

    max_attempts: int = 3
    initial_backoff_seconds: float = 2.0
    max_backoff_seconds: float = 30.0
    rate_window_seconds: float = 1.0
    max_claims_per_window: int = 5
    lease_seconds: float = 10.0
    max_records: int = 10_000

    def __post_init__(self) -> None:
        for value in (self.max_attempts, self.max_claims_per_window, self.max_records):
            if type(value) is not int or value <= 0:
                raise ValueError("outbox count limits must be positive integers")
        for seconds in (
            self.initial_backoff_seconds,
            self.max_backoff_seconds,
            self.rate_window_seconds,
            self.lease_seconds,
        ):
            if not isinstance(seconds, (int, float)) or not isfinite(seconds) or seconds <= 0:
                raise ValueError("outbox time limits must be finite and positive")
        if self.initial_backoff_seconds > self.max_backoff_seconds:
            raise ValueError("maximum backoff must not be smaller than initial backoff")


@dataclass(frozen=True, slots=True)
class NotificationRecord:
    """Sanitized immutable view of an outbox record; no source payload."""

    idempotency_key: UUID
    kind: NoticeKind
    priority: Priority
    state: DeliveryState
    attempts: int
    created_at: float
    next_attempt_at: float | None
    accepted_at: float | None
    acceptance_latency_seconds: float | None


@dataclass(frozen=True, slots=True)
class DeliveryClaim:
    """A single lease for a static, non-sensitive message; never an API call."""

    idempotency_key: UUID
    kind: NoticeKind
    priority: Priority
    message: str
    attempt_number: int


@dataclass(frozen=True, slots=True)
class AcceptanceMetrics:
    """Nearest-rank synthetic acceptance latency, NOT Telegram delivery SLA."""

    accepted_count: int
    p95_seconds: float | None
    p99_seconds: float | None


@dataclass(slots=True, repr=False)
class _Entry:
    idempotency_key: UUID
    kind: NoticeKind
    priority: Priority
    message: str
    sequence: int
    created_at: float
    next_attempt_at: float | None
    state: DeliveryState = DeliveryState.PENDING
    attempts: int = 0
    lease_deadline: float | None = None
    accepted_at: float | None = None

    def snapshot(self) -> NotificationRecord:
        latency = None if self.accepted_at is None else self.accepted_at - self.created_at
        return NotificationRecord(
            idempotency_key=self.idempotency_key,
            kind=self.kind,
            priority=self.priority,
            state=self.state,
            attempts=self.attempts,
            created_at=self.created_at,
            next_attempt_at=self.next_attempt_at,
            accepted_at=self.accepted_at,
            acceptance_latency_seconds=latency,
        )


class NotificationOutbox:
    """An atomic in-memory scheduler. All input times are monotonic seconds.

    Claims consume a rate-limit slot, even on failure; a claim expires after
    ``lease_seconds`` and counts as one failed attempt. No exceptions or source
    messages are accepted by ``fail``. Caller chooses the retryability flag
    and optionally the provider's ``retry_after_seconds`` delay floor.
    """

    def __init__(self, policy: OutboxPolicy | None = None) -> None:
        self._policy = policy if policy is not None else OutboxPolicy()
        self._entries: dict[UUID, _Entry] = {}
        self._claim_times: deque[float] = deque()
        self._sequence = 0
        self._last_time: float | None = None
        self._lock = RLock()

    def enqueue(self, request: NotificationRequest, *, now: float) -> NotificationRecord:
        """Enqueue only the allowlisted kind, discarding all raw event context."""

        with self._lock:
            self._observe(now)
            if (
                not isinstance(request, NotificationRequest)
                or type(request.idempotency_key) is not UUID
                or not isinstance(request.kind, NoticeKind)
            ):
                raise ValueError("notification requires an opaque UUID and a known kind")
            existing = self._entries.get(request.idempotency_key)
            if existing is not None:
                if existing.kind != request.kind:
                    raise IdempotencyConflict("idempotency key reused for a different kind")
                return existing.snapshot()
            if len(self._entries) >= self._policy.max_records:
                raise OutboxCapacityError("outbox record capacity exhausted")
            priority, message = _SAFE_NOTICE[request.kind]
            self._sequence += 1
            record = _Entry(
                idempotency_key=request.idempotency_key,
                kind=request.kind,
                priority=priority,
                message=message,
                sequence=self._sequence,
                created_at=now,
                next_attempt_at=now,
            )
            self._entries[request.idempotency_key] = record
            return record.snapshot()

    def get(self, idempotency_key: UUID) -> NotificationRecord | None:
        with self._lock:
            entry = self._entries.get(idempotency_key)
            return entry.snapshot() if entry is not None else None

    def records(self) -> tuple[NotificationRecord, ...]:
        with self._lock:
            return tuple(record.snapshot() for record in self._entries.values())

    def claim_ready(self, *, now: float, limit: int = 100) -> tuple[DeliveryClaim, ...]:
        """Atomically claim due messages by descending priority then FIFO.

        Claiming does not transmit anything. A future transport must separately
        report an acceptance or failure, and must not forward source context.
        """

        with self._lock:
            self._observe(now)
            if type(limit) is not int or limit <= 0:
                raise ValueError("claim limit must be a positive integer")
            self._expire_claims(now)
            cutoff = now - self._policy.rate_window_seconds
            while self._claim_times and self._claim_times[0] <= cutoff:
                self._claim_times.popleft()
            budget = min(limit, self._policy.max_claims_per_window - len(self._claim_times))
            if budget <= 0:
                return ()

            due = sorted(
                (
                    entry
                    for entry in self._entries.values()
                    if entry.state is DeliveryState.PENDING
                    and entry.next_attempt_at is not None
                    and entry.next_attempt_at <= now
                ),
                key=lambda entry: (-entry.priority, entry.sequence),
            )
            claimed: list[DeliveryClaim] = []
            for entry in due[:budget]:
                entry.state = DeliveryState.CLAIMED
                entry.next_attempt_at = None
                entry.attempts += 1
                entry.lease_deadline = now + self._policy.lease_seconds
                self._claim_times.append(now)
                claimed.append(
                    DeliveryClaim(
                        idempotency_key=entry.idempotency_key,
                        kind=entry.kind,
                        priority=entry.priority,
                        message=entry.message,
                        attempt_number=entry.attempts,
                    )
                )
            return tuple(claimed)

    def accept(self, claim: DeliveryClaim, *, now: float) -> NotificationRecord:
        """Record local/simulated acceptance; never claim human receipt."""

        with self._lock:
            self._observe(now)
            entry = self._require_claim(claim, now)
            entry.state = DeliveryState.ACCEPTED
            entry.lease_deadline = None
            entry.accepted_at = now
            return entry.snapshot()

    def fail(
        self,
        claim: DeliveryClaim,
        *,
        now: float,
        retryable: bool = True,
        retry_after_seconds: float | None = None,
    ) -> NotificationRecord:
        """Retry with bounded backoff or exhaust, without storing error text."""

        with self._lock:
            self._observe(now)
            if type(retryable) is not bool:
                raise ValueError("retryable must be boolean")
            if retry_after_seconds is not None and (
                not isinstance(retry_after_seconds, (int, float))
                or not isfinite(retry_after_seconds)
                or retry_after_seconds < 0
            ):
                raise ValueError("retry_after must be finite and nonnegative")
            entry = self._require_claim(claim, now)
            self._schedule_failure(entry, now, retryable, retry_after_seconds)
            return entry.snapshot()

    def run_dry_run(self, *, now: float, limit: int = 100) -> tuple[DeliveryClaim, ...]:
        """Consume and accept due claims locally, without a Telegram adapter."""

        with self._lock:
            claims = self.claim_ready(now=now, limit=limit)
            for claim in claims:
                self.accept(claim, now=now)
            return claims

    def acceptance_metrics(self) -> AcceptanceMetrics:
        """Report nearest-rank p95/p99 of simulated accepted claims only."""

        with self._lock:
            durations = sorted(
                entry.accepted_at - entry.created_at
                for entry in self._entries.values()
                if entry.accepted_at is not None
            )
            if not durations:
                return AcceptanceMetrics(accepted_count=0, p95_seconds=None, p99_seconds=None)
            p95 = durations[ceil(0.95 * len(durations)) - 1]
            p99 = durations[ceil(0.99 * len(durations)) - 1]
            return AcceptanceMetrics(len(durations), p95, p99)

    def _observe(self, now: float) -> None:
        if not isinstance(now, (int, float)) or not isfinite(now) or now < 0:
            raise ValueError("now must be a finite nonnegative monotonic timestamp")
        if self._last_time is not None and now < self._last_time:
            raise ValueError("outbox time must not move backwards")
        self._last_time = now

    def _require_claim(self, claim: DeliveryClaim, now: float) -> _Entry:
        if not isinstance(claim, DeliveryClaim):
            raise InvalidClaim("claim is invalid or stale")
        entry = self._entries.get(claim.idempotency_key)
        if (
            entry is None
            or entry.state is not DeliveryState.CLAIMED
            or entry.attempts != claim.attempt_number
            or entry.kind != claim.kind
            or entry.priority != claim.priority
            or entry.message != claim.message
            or entry.lease_deadline is None
            or now >= entry.lease_deadline
        ):
            raise InvalidClaim("claim is invalid or stale")
        return entry

    def _expire_claims(self, now: float) -> None:
        for entry in self._entries.values():
            if (
                entry.state is DeliveryState.CLAIMED
                and entry.lease_deadline is not None
                and entry.lease_deadline <= now
            ):
                self._schedule_failure(entry, now, retryable=True, retry_after_seconds=None)

    def _schedule_failure(
        self,
        entry: _Entry,
        now: float,
        retryable: bool,
        retry_after_seconds: float | None,
    ) -> None:
        entry.lease_deadline = None
        if not retryable or entry.attempts >= self._policy.max_attempts:
            entry.state = DeliveryState.EXHAUSTED
            entry.next_attempt_at = None
            return
        # Saturate *before* exponentiation to avoid float overflow even if a
        # caller has configured an unusually large maximum attempt count.
        exponent = entry.attempts - 1
        saturation = log2(self._policy.max_backoff_seconds) - log2(
            self._policy.initial_backoff_seconds
        )
        if exponent >= saturation:
            backoff = self._policy.max_backoff_seconds
        else:
            backoff = min(
                self._policy.max_backoff_seconds,
                ldexp(self._policy.initial_backoff_seconds, exponent),
            )
        delay = max(backoff, retry_after_seconds or 0)
        next_time = now + delay
        if not isfinite(next_time):
            entry.state = DeliveryState.EXHAUSTED
            entry.next_attempt_at = None
            return
        entry.state = DeliveryState.PENDING
        entry.next_attempt_at = next_time
