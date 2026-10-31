"""Durable synthetic notification scheduler; no transport or network code.

Wall-clock Unix seconds are injected, because monotonic process times cannot
survive restarts. SQLite serializes writers with BEGIN IMMEDIATE; lease tokens
fence late acknowledgements from a prior process/attempt.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.resources import files
from math import ceil, isfinite, ldexp, log2
from pathlib import Path
from uuid import UUID, uuid4

from boca_socios.notify.outbox import (
    _SAFE_NOTICE,
    AcceptanceMetrics,
    DeliveryState,
    IdempotencyConflict,
    InvalidClaim,
    NoticeKind,
    NotificationRecord,
    NotificationRequest,
    OutboxCapacityError,
    OutboxPolicy,
    Priority,
)
from boca_socios.storage.database import Database

_RECORD = (
    "SELECT idempotency_key, kind, state, attempts, created_at, next_attempt_at, accepted_at "
    "FROM notification_outbox"
)


@dataclass(frozen=True, slots=True, repr=False)
class SqliteDeliveryClaim:
    idempotency_key: UUID
    kind: NoticeKind
    priority: Priority
    message: str
    attempt_number: int
    lease_token: UUID

    def __repr__(self) -> str:
        return "SqliteDeliveryClaim(<lease omitted>)"


class SqliteNotificationOutbox:
    """Store only UUID/kind/state/timing; source payloads never enter SQLite."""

    def __init__(self, path: Path, policy: OutboxPolicy | None = None) -> None:
        self._db = Database(path)
        self._policy = policy if policy is not None else OutboxPolicy()

    def migrate(self) -> None:
        """Apply the additive version-2 schema after the existing foundation."""
        self._db.migrate()
        sql = (
            files("boca_socios.storage.migrations")
            .joinpath("0002_notification_outbox.sql")
            .read_text(encoding="utf-8")
        )
        digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        with self._write() as connection:
            row = connection.execute(
                "SELECT checksum FROM schema_migrations WHERE version = 2"
            ).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("migration checksum mismatch: durable outbox")
                return
            # This reviewed SQL file contains only simple DDL statements and
            # no string literal with a semicolon. execute() keeps the version
            # record and every DDL statement inside one BEGIN IMMEDIATE.
            for statement in sql.split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, checksum) VALUES (2, ?)", (digest,)
            )

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _time(now: float) -> float:
        if not isinstance(now, (int, float)) or not isfinite(now) or now < 0:
            raise ValueError("now must be finite nonnegative Unix seconds")
        return float(now)

    @staticmethod
    def _record(row: tuple[object, ...]) -> NotificationRecord:
        accepted = None if row[6] is None else float(str(row[6]))
        created = float(str(row[4]))
        kind = NoticeKind(str(row[1]))
        return NotificationRecord(
            idempotency_key=UUID(str(row[0])),
            kind=kind,
            priority=_SAFE_NOTICE[kind][0],
            state=DeliveryState(str(row[2])),
            attempts=int(str(row[3])),
            created_at=created,
            next_attempt_at=None if row[5] is None else float(str(row[5])),
            accepted_at=accepted,
            acceptance_latency_seconds=None if accepted is None else accepted - created,
        )

    def enqueue(
        self, request: NotificationRequest, *, now: float, ttl_seconds: float = 3600
    ) -> NotificationRecord:
        now = self._time(now)
        if (
            not isinstance(ttl_seconds, (int, float))
            or not isfinite(ttl_seconds)
            or ttl_seconds <= 0
        ):
            raise ValueError("ttl_seconds must be finite and positive")
        expires = now + ttl_seconds
        if not isfinite(expires) or expires <= now:
            raise ValueError("ttl_seconds exceeds the timestamp range")
        if (
            not isinstance(request, NotificationRequest)
            or type(request.idempotency_key) is not UUID
            or not isinstance(request.kind, NoticeKind)
        ):
            raise ValueError("notification requires an opaque UUID and a known kind")
        key = str(request.idempotency_key)
        with self._write() as connection:
            row = connection.execute(f"{_RECORD} WHERE idempotency_key = ?", (key,)).fetchone()
            if row is not None:
                record = self._record(row)
                if record.kind is not request.kind:
                    raise IdempotencyConflict("idempotency key reused for a different kind")
                return record
            count = connection.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()
            if count is None or count[0] >= self._policy.max_records:
                raise OutboxCapacityError("outbox record capacity exhausted")
            priority = _SAFE_NOTICE[request.kind][0]
            connection.execute(
                """INSERT INTO notification_outbox
                   (idempotency_key, kind, priority, state, created_at, expires_at,
                    next_attempt_at)
                   VALUES (?, ?, ?, 'pending', ?, ?, ?)""",
                (key, request.kind.value, int(priority), now, expires, now),
            )
            inserted = connection.execute(f"{_RECORD} WHERE idempotency_key = ?", (key,)).fetchone()
            assert inserted is not None
            return self._record(inserted)

    def get(self, idempotency_key: UUID) -> NotificationRecord | None:
        if type(idempotency_key) is not UUID:
            raise ValueError("idempotency key must be UUID")
        with self._db.connection() as connection:
            row = connection.execute(
                f"{_RECORD} WHERE idempotency_key = ?", (str(idempotency_key),)
            ).fetchone()
            return None if row is None else self._record(row)

    def claim_ready(self, *, now: float, limit: int = 100) -> tuple[SqliteDeliveryClaim, ...]:
        now = self._time(now)
        if type(limit) is not int or limit <= 0:
            raise ValueError("claim limit must be a positive integer")
        lease_until = now + self._policy.lease_seconds
        if not isfinite(lease_until) or lease_until <= now:
            raise ValueError("lease deadline exceeds the timestamp range")
        with self._write() as connection:
            connection.execute(
                """UPDATE notification_outbox SET state='exhausted', next_attempt_at=NULL,
                   lease_token=NULL, claimed_at=NULL, lease_until=NULL
                   WHERE state IN ('pending', 'claimed') AND expires_at <= ?""",
                (now,),
            )
            expired_claims = connection.execute(
                """SELECT idempotency_key, attempts, expires_at FROM notification_outbox
                   WHERE state='claimed' AND lease_until <= ?""",
                (now,),
            ).fetchall()
            for key, attempts, expires in expired_claims:
                self._schedule_failure(connection, str(key), int(attempts), float(expires), now)
            connection.execute(
                "DELETE FROM notification_claim_windows WHERE attempted_at <= ?",
                (now - self._policy.rate_window_seconds,),
            )
            usage = connection.execute("SELECT COUNT(*) FROM notification_claim_windows").fetchone()
            remaining = self._policy.max_claims_per_window - (0 if usage is None else usage[0])
            budget = min(limit, remaining)
            if budget <= 0:
                return ()
            due = connection.execute(
                """SELECT idempotency_key, kind, priority, attempts
                   FROM notification_outbox
                   WHERE state='pending' AND next_attempt_at <= ? AND expires_at > ?
                   ORDER BY priority DESC, sequence ASC LIMIT ?""",
                (now, now, budget),
            ).fetchall()
            claims: list[SqliteDeliveryClaim] = []
            for key, kind_raw, priority_raw, attempts in due:
                kind = NoticeKind(str(kind_raw))
                priority, message = _SAFE_NOTICE[kind]
                if int(priority_raw) != int(priority):
                    raise ValueError("stored notification priority mismatch")
                lease_token = uuid4()
                attempt_number = int(attempts) + 1
                connection.execute(
                    """UPDATE notification_outbox SET state='claimed', attempts=?,
                       next_attempt_at=NULL, lease_token=?, claimed_at=?, lease_until=?
                       WHERE idempotency_key=?""",
                    (attempt_number, str(lease_token), now, lease_until, key),
                )
                connection.execute(
                    "INSERT INTO notification_claim_windows(attempted_at) VALUES (?)", (now,)
                )
                claims.append(
                    SqliteDeliveryClaim(
                        UUID(str(key)), kind, priority, message, attempt_number, lease_token
                    )
                )
            return tuple(claims)

    def _validate_claim(
        self, connection: sqlite3.Connection, claim: SqliteDeliveryClaim, now: float
    ) -> tuple[str, int, float]:
        if not isinstance(claim, SqliteDeliveryClaim):
            raise InvalidClaim("claim is invalid or stale")
        row = connection.execute(
            """SELECT kind, priority, state, attempts, lease_token, lease_until,
                      expires_at, claimed_at
               FROM notification_outbox WHERE idempotency_key=?""",
            (str(claim.idempotency_key),),
        ).fetchone()
        if row is None:
            raise InvalidClaim("claim is invalid or stale")
        kind = NoticeKind(str(row[0]))
        priority, message = _SAFE_NOTICE[kind]
        if (
            row[2] != DeliveryState.CLAIMED.value
            or row[3] != claim.attempt_number
            or row[4] != str(claim.lease_token)
            or row[5] is None
            or row[7] is None
            or now < row[7]
            or now >= row[5]
            or now >= row[6]
            or claim.kind is not kind
            or claim.priority != priority
            or claim.message != message
            or row[1] != int(priority)
        ):
            raise InvalidClaim("claim is invalid or stale")
        return str(claim.idempotency_key), int(row[3]), float(row[6])

    def accept(self, claim: SqliteDeliveryClaim, *, now: float) -> NotificationRecord:
        now = self._time(now)
        with self._write() as connection:
            key, _, _ = self._validate_claim(connection, claim, now)
            connection.execute(
                """UPDATE notification_outbox SET state='accepted', accepted_at=?,
                   lease_token=NULL, claimed_at=NULL, lease_until=NULL
                   WHERE idempotency_key=?""",
                (now, key),
            )
            row = connection.execute(f"{_RECORD} WHERE idempotency_key=?", (key,)).fetchone()
            assert row is not None
            return self._record(row)

    def fail(
        self,
        claim: SqliteDeliveryClaim,
        *,
        now: float,
        retryable: bool = True,
        retry_after_seconds: float | None = None,
    ) -> NotificationRecord:
        now = self._time(now)
        if type(retryable) is not bool:
            raise ValueError("retryable must be boolean")
        if retry_after_seconds is not None and (
            not isinstance(retry_after_seconds, (int, float))
            or not isfinite(retry_after_seconds)
            or retry_after_seconds < 0
        ):
            raise ValueError("retry_after must be finite and nonnegative")
        with self._write() as connection:
            key, attempts, expires = self._validate_claim(connection, claim, now)
            self._schedule_failure(
                connection, key, attempts, expires, now, retryable, retry_after_seconds
            )
            row = connection.execute(f"{_RECORD} WHERE idempotency_key=?", (key,)).fetchone()
            assert row is not None
            return self._record(row)

    def _schedule_failure(
        self,
        connection: sqlite3.Connection,
        key: str,
        attempts: int,
        expires: float,
        now: float,
        retryable: bool = True,
        retry_after_seconds: float | None = None,
    ) -> None:
        next_attempt: float | None = None
        if retryable and attempts < self._policy.max_attempts:
            saturation = log2(self._policy.max_backoff_seconds) - log2(
                self._policy.initial_backoff_seconds
            )
            backoff = (
                self._policy.max_backoff_seconds
                if attempts - 1 >= saturation
                else min(
                    self._policy.max_backoff_seconds,
                    ldexp(self._policy.initial_backoff_seconds, attempts - 1),
                )
            )
            candidate = now + max(backoff, retry_after_seconds or 0)
            if isfinite(candidate) and candidate < expires:
                next_attempt = candidate
        connection.execute(
            """UPDATE notification_outbox SET state=?, next_attempt_at=?,
               lease_token=NULL, claimed_at=NULL, lease_until=NULL
               WHERE idempotency_key=?""",
            ("pending" if next_attempt is not None else "exhausted", next_attempt, key),
        )

    def acceptance_metrics(self) -> AcceptanceMetrics:
        """Local/simulated acknowledgement latency; never provider delivery."""
        with self._db.connection() as connection:
            rows = connection.execute(
                """SELECT accepted_at - created_at FROM notification_outbox
                   WHERE state='accepted' ORDER BY accepted_at - created_at"""
            ).fetchall()
        latencies = [float(row[0]) for row in rows]
        if not latencies:
            return AcceptanceMetrics(0, None, None)
        return AcceptanceMetrics(
            len(latencies),
            latencies[ceil(len(latencies) * 0.95) - 1],
            latencies[ceil(len(latencies) * 0.99) - 1],
        )
