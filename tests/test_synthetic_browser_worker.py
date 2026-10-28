from __future__ import annotations

import asyncio

import pytest

from boca_socios.browser.contracts import (
    SimulationNotice,
    SimulationOutcome,
    SyntheticBrowserWorkflow,
)
from boca_socios.domain.policy import TicketIntent


class FakeIntentStore:
    def __init__(self) -> None:
        self.requests: dict[tuple[str, str], str] = {}

    def ensure_ticket_intent(self, intent: TicketIntent) -> str:
        key = (intent.member_id, intent.event_id)
        return self.requests.setdefault(key, f"intent-{len(self.requests) + 1}")


class FakeBrowser:
    def __init__(self) -> None:
        self.calls = 0

    async def simulate_general_reservation(self) -> SimulationOutcome:
        self.calls += 1
        return SimulationOutcome.RESERVED_IN_SIMULATOR


class FakeNotifications:
    def __init__(self) -> None:
        self.notices: list[SimulationNotice] = []

    def publish_simulation_notice(self, notice: SimulationNotice) -> None:
        self.notices.append(notice)


def test_synthetic_workflow_reuses_one_logical_intent() -> None:
    store, browser, notifications = FakeIntentStore(), FakeBrowser(), FakeNotifications()
    workflow = SyntheticBrowserWorkflow(intents=store, browser=browser, notifications=notifications)
    intent = TicketIntent(member_id="synthetic-member", event_id="synthetic-match")
    first = asyncio.run(workflow.run(intent))
    second = asyncio.run(workflow.run(intent))
    assert first == second
    assert len(store.requests) == 1
    assert browser.calls == 2  # This is a dry-run, not an external reservation.
    assert len(notifications.notices) == 2
    assert notifications.notices[0].outcome is SimulationOutcome.RESERVED_IN_SIMULATOR


def test_reject_invalid_quantity_before_any_browser_action() -> None:
    store, browser, notifications = FakeIntentStore(), FakeBrowser(), FakeNotifications()
    workflow = SyntheticBrowserWorkflow(intents=store, browser=browser, notifications=notifications)
    with pytest.raises(ValueError, match="exactly one"):
        asyncio.run(workflow.run(TicketIntent("synthetic-member", "synthetic-match", quantity=2)))
    assert not store.requests and browser.calls == 0 and not notifications.notices
