"""Explicit, single-attempt Telegram dispatch with a durable pre-send fence.

An intent is committed before the network call. A crash in the uncertain
interval leaves a visible needs-review record and cannot cause an automatic
second send. No Telegram worker is started by importing this module.
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import stat
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from importlib.resources import files
from math import isfinite

from boca_socios.notify.sqlite_outbox import SqliteDeliveryClaim, SqliteNotificationOutbox
from boca_socios.notify.telegram_transport import TelegramAck, TelegramNotice, TelegramSender


class TelegramDeliveryStopped(RuntimeError):
    """Redacted storage/lease error; no second send can be assumed safe."""


@dataclass(frozen=True, slots=True)
class TelegramDeliveryReport:
    attempted: int
    api_accepted: int
    ambiguous: int


class TelegramDeliveryCoordinator:
    """Opt-in sender; API acceptance is distinct from human receipt/read."""

    def __init__(
        self,
        outbox: SqliteNotificationOutbox,
        transport: TelegramSender,
        clock: Callable[[], float],
        *,
        max_per_tick: int = 5,
        timeout_seconds: float = 5.0,
    ) -> None:
        if type(max_per_tick) is not int or not 1 <= max_per_tick <= 10:
            raise ValueError("Telegram tick capacity must be between 1 and 10")
        if (
            type(timeout_seconds) not in (int, float)
            or not isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 5
        ):
            raise ValueError("Telegram timeout must be finite and in (0, 5]")
        self._outbox = outbox
        self._transport = transport
        self._clock = clock
        self._max_per_tick = max_per_tick
        self._timeout = timeout_seconds

    def prepare_storage(self) -> None:
        """Explicit opt-in schema migration; never invoked by construction/tick."""
        self._outbox.migrate()
        sql = (
            files("boca_socios.storage.migrations")
            .joinpath("0007_telegram_delivery.sql")
            .read_text(encoding="utf-8")
        )
        digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        with self._outbox._write() as connection:
            row = connection.execute(
                "SELECT checksum FROM schema_migrations WHERE version = 7"
            ).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("migration checksum mismatch: Telegram delivery")
                return
            for statement in sql.split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, checksum) VALUES (7, ?)", (digest,)
            )

    def _now(self) -> float:
        now = self._clock()
        if type(now) not in (int, float) or not isfinite(now) or now < 0:
            raise TelegramDeliveryStopped("Telegram clock invalid")
        return float(now)

    def _require_storage(self) -> None:
        sql = (
            files("boca_socios.storage.migrations")
            .joinpath("0007_telegram_delivery.sql")
            .read_text(encoding="utf-8")
        )
        digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        try:
            path = self._outbox.database.path
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                raise RuntimeError("Telegram storage is not prepared")
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
                row = connection.execute(
                    "SELECT checksum FROM schema_migrations WHERE version = 7"
                ).fetchone()
                table = connection.execute(
                    """SELECT 1 FROM sqlite_master WHERE type='table'
                       AND name='telegram_delivery_attempts'"""
                ).fetchone()
        except (OSError, sqlite3.DatabaseError):
            raise RuntimeError("Telegram storage is not prepared") from None
        if row is None or table is None:
            raise RuntimeError("Telegram storage is not prepared")
        if row[0] != digest:
            raise TelegramDeliveryStopped("Telegram storage checksum mismatch")

    def _prepare(self, claim: SqliteDeliveryClaim) -> None:
        try:
            with self._outbox._write() as connection:
                now = self._now()
                self._outbox._validate_claim(connection, claim, now)
                connection.execute(
                    """INSERT INTO telegram_delivery_attempts
                       (idempotency_key, attempt_number, state, prepared_at)
                       VALUES (?, ?, 'prepared', ?)""",
                    (str(claim.idempotency_key), claim.attempt_number, now),
                )
        except Exception:
            raise TelegramDeliveryStopped("Telegram preparation failed") from None

    def _settle(self, claim: SqliteDeliveryClaim, ack: TelegramAck | None) -> None:
        try:
            with self._outbox._write() as connection:
                now = self._now()
                key, attempts, expires = self._outbox._validate_claim(connection, claim, now)
                marker = connection.execute(
                    "SELECT state, attempt_number FROM telegram_delivery_attempts WHERE idempotency_key=?",
                    (key,),
                ).fetchone()
                if marker != ("prepared", claim.attempt_number):
                    raise ValueError("Telegram intent changed")
                if ack is not None:
                    connection.execute(
                        """UPDATE notification_outbox SET state='accepted', accepted_at=?,
                           lease_token=NULL, claimed_at=NULL, lease_until=NULL
                           WHERE idempotency_key=?""",
                        (now, key),
                    )
                    state, message_id = "api_accepted", ack.message_id
                else:
                    self._outbox._schedule_failure(
                        connection, key, attempts, expires, now, retryable=False
                    )
                    state, message_id = "ambiguous", None
                connection.execute(
                    """UPDATE telegram_delivery_attempts SET state=?, settled_at=?,
                       provider_message_id=? WHERE idempotency_key=?""",
                    (state, now, message_id, key),
                )
        except Exception:
            # The prepared marker remains durable even when settlement fails.
            raise TelegramDeliveryStopped("Telegram settlement failed; review required") from None

    async def tick(self) -> TelegramDeliveryReport:
        self._require_storage()
        try:
            self._transport.preflight()
        except Exception:
            raise TelegramDeliveryStopped("Telegram private configuration unavailable") from None
        accepted = ambiguous = 0
        for _ in range(self._max_per_tick):
            try:
                claims = self._outbox.claim_ready(now=self._now(), limit=1)
            except Exception:
                raise TelegramDeliveryStopped("Telegram claim failed") from None
            if not claims:
                break
            claim = claims[0]
            self._prepare(claim)
            try:
                result = await asyncio.wait_for(
                    self._transport.send(TelegramNotice(claim.idempotency_key, claim.kind)),
                    timeout=self._timeout,
                )
                ack = result if isinstance(result, TelegramAck) else None
            except asyncio.CancelledError:
                self._settle(claim, None)
                raise
            except Exception:
                ack = None
            self._settle(claim, ack)
            if ack is None:
                ambiguous += 1
            else:
                accepted += 1
        return TelegramDeliveryReport(accepted + ambiguous, accepted, ambiguous)
