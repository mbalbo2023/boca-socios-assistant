"""Explicit workflow ports for a simulation-only browser worker."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from boca_socios.domain.policy import TicketIntent


class SimulationOutcome(StrEnum):
    """A local test result; deliberately not a real ticket status."""

    RESERVED_IN_SIMULATOR = "reserved_in_simulator"


@dataclass(frozen=True, slots=True)
class SimulationReceipt:
    request_id: str
    outcome: SimulationOutcome


@dataclass(frozen=True, slots=True)
class SimulationNotice:
    """Internal correlation only: no member ID, event ID or browser state."""

    request_id: str
    outcome: SimulationOutcome


class IntentRepositoryPort(Protocol):
    """May be backed by an idempotent SQLite intent in a later integration."""

    def ensure_ticket_intent(self, intent: TicketIntent) -> str: ...


class NotificationPort(Protocol):
    """Eventually backed by the durable outbox, not by network I/O here."""

    def publish_simulation_notice(self, notice: SimulationNotice) -> None: ...


class SyntheticBrowserPort(Protocol):
    """No live URL, credential or session argument is allowed."""

    async def simulate_general_reservation(self) -> SimulationOutcome: ...


class SyntheticBrowserWorkflow:
    """Validated one-ticket intent, synthetic browser, and redacted notification."""

    def __init__(
        self,
        *,
        intents: IntentRepositoryPort,
        browser: SyntheticBrowserPort,
        notifications: NotificationPort,
    ) -> None:
        self._intents = intents
        self._browser = browser
        self._notifications = notifications

    async def run(self, intent: TicketIntent) -> SimulationReceipt:
        intent.validate()
        request_id = self._intents.ensure_ticket_intent(intent)
        if not request_id:
            raise ValueError("intent repository returned an empty request_id")
        outcome = await self._browser.simulate_general_reservation()
        if outcome is not SimulationOutcome.RESERVED_IN_SIMULATOR:
            raise ValueError("unexpected synthetic browser outcome")
        self._notifications.publish_simulation_notice(
            SimulationNotice(
                request_id=request_id,
                outcome=outcome,
            )
        )
        return SimulationReceipt(request_id=request_id, outcome=outcome)
