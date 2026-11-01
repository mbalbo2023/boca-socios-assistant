"""Synthetic rehearsals only: no real transport, runtime wiring or exactly-once promise.

A hard crash after a synthetic send but before settlement leaves an expiring
lease that the existing outbox retries. Real delivery requires a separate durable
ambiguity/reconciliation design before this contract can be reused.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Protocol
from uuid import UUID

from boca_socios.notify.outbox import NoticeKind
from boca_socios.notify.sqlite_outbox import SqliteDeliveryClaim, SqliteNotificationOutbox


class SyntheticStatus(StrEnum):
    ACCEPTED = "accepted"
    RETRYABLE = "retryable"
    PERMANENT = "permanent"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class SyntheticResult:
    status: SyntheticStatus
    retry_after_seconds: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, SyntheticStatus):
            raise ValueError("unknown synthetic result")
        delay = self.retry_after_seconds
        if delay is not None and (
            self.status is not SyntheticStatus.RETRYABLE
            or type(delay) not in (int, float)
            or not isfinite(delay)
            or delay < 0
        ):
            raise ValueError("retry delay requires a retryable result and finite nonnegative seconds")


@dataclass(frozen=True, slots=True, repr=False)
class SyntheticNotice:
    """Allowlisted notice only; no lease token, recipient, credentials or source payload."""

    idempotency_key: UUID
    kind: NoticeKind
    message: str

    def __repr__(self) -> str:
        return "SyntheticNotice(<content omitted>)"


class SyntheticTransport(Protocol):
    """Test port only; implementations must cooperate with asyncio cancellation.

    No real delivery implementation is supplied or permitted by this rehearsal
    contract. ACCEPTED means a local synthetic result, never provider receipt.
    """

    async def send(self, notice: SyntheticNotice) -> SyntheticResult: ...


@dataclass(frozen=True, slots=True)
class DispatchReport:
    """Counts of settled synthetic outcomes, not proof of provider delivery.

    A retryable outcome can exhaust the outbox's existing attempt/TTL budget.
    """

    attempted: int
    accepted: int
    retryable: int
    permanent: int
    ambiguous: int


class DispatchStopped(RuntimeError):
    """Redacted storage/lease failure; the tick stops without claiming more work."""


class SyntheticDispatcher:
    """Bounded offline experiment over existing durable leases and tombstones.

    Explicit ambiguity, exceptions and timeouts exhaust the active claim. A hard
    process crash cannot be reconciled by the existing schema and may be retried
    after lease expiry. This class must not be wired to runtime or real delivery.
    """

    def __init__(
        self,
        outbox: SqliteNotificationOutbox,
        transport: SyntheticTransport,
        clock: Callable[[], float],
        *,
        max_per_tick: int = 10,
        timeout_seconds: float = 1,
    ) -> None:
        if type(max_per_tick) is not int or not 1 <= max_per_tick <= 100:
            raise ValueError("max_per_tick must be an integer between 1 and 100")
        if (
            type(timeout_seconds) not in (int, float)
            or not isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 5
        ):
            raise ValueError("timeout_seconds must be finite and in (0, 5]")
        self._outbox = outbox
        self._transport = transport
        self._clock = clock
        self._max_per_tick = max_per_tick
        self._timeout = timeout_seconds

    def _settle(self, claim: SqliteDeliveryClaim, result: SyntheticResult) -> None:
        try:
            now = self._clock()
            if result.status is SyntheticStatus.ACCEPTED:
                self._outbox.accept(claim, now=now)
            else:
                self._outbox.fail(
                    claim,
                    now=now,
                    retryable=result.status is SyntheticStatus.RETRYABLE,
                    retry_after_seconds=result.retry_after_seconds,
                )
        except Exception:
            # Never expose transport text, database paths, tokens or payloads.
            raise DispatchStopped("synthetic notification settlement failed") from None

    async def tick(self) -> DispatchReport:
        counts = dict.fromkeys(SyntheticStatus, 0)
        for _ in range(self._max_per_tick):
            try:
                claims = self._outbox.claim_ready(now=self._clock(), limit=1)
            except Exception:
                raise DispatchStopped("synthetic notification claim failed") from None
            if not claims:
                break
            claim = claims[0]
            notice = SyntheticNotice(claim.idempotency_key, claim.kind, claim.message)
            try:
                result = await asyncio.wait_for(self._transport.send(notice), timeout=self._timeout)
                if not isinstance(result, SyntheticResult):
                    result = SyntheticResult(SyntheticStatus.AMBIGUOUS)
            except asyncio.CancelledError:
                self._settle(claim, SyntheticResult(SyntheticStatus.AMBIGUOUS))
                raise
            except Exception:
                result = SyntheticResult(SyntheticStatus.AMBIGUOUS)
            self._settle(claim, result)
            counts[result.status] += 1
        return DispatchReport(
            attempted=sum(counts.values()),
            accepted=counts[SyntheticStatus.ACCEPTED],
            retryable=counts[SyntheticStatus.RETRYABLE],
            permanent=counts[SyntheticStatus.PERMANENT],
            ambiguous=counts[SyntheticStatus.AMBIGUOUS],
        )
