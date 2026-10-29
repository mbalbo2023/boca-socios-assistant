from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from runpy import run_path
from types import ModuleType

import pytest

from boca_socios.browser.contracts import (
    SimulationNotice,
    SimulationOutcome,
    SyntheticBrowserWorkflow,
)
from boca_socios.browser.synthetic import (
    STEPS,
    SYNTHETIC_HTML,
    SyntheticFlowError,
    SyntheticTicketScenario,
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


class FakeLocator:
    def __init__(self, page: FakePage, *, action: str | None = None) -> None:
        self.page = page
        self.action = action

    async def inner_text(self, *, timeout: float) -> str:
        assert timeout == 5_000
        return self.page.stage

    async def click(self, *, timeout: float) -> None:
        assert timeout == 5_000
        matches = [step for step in STEPS if step.before == self.page.stage]
        if len(matches) != 1 or matches[0].action != self.action:
            raise SyntheticFlowError("invalid fake button")
        self.page.stage = matches[0].after
        self.page.actions.append(self.action or "")


class FakePage:
    """No goto, network, storage or credential methods are available."""

    def __init__(self, *, tamper: bool = False) -> None:
        self.stage = "not_started"
        self.actions: list[str] = []
        self.tamper = tamper

    async def set_content(self, html: str, *, wait_until: str, timeout: float) -> None:
        assert html == SYNTHETIC_HTML
        assert "https://" not in html and "http://" not in html
        assert wait_until == "load" and timeout == 5_000
        self.stage = "tampered" if self.tamper else "prequeue"

    def locator(self, selector: str) -> FakeLocator:
        assert selector == "#stage"
        return FakeLocator(self)

    def get_by_role(self, role: str, *, name: str) -> FakeLocator:
        assert role == "button"
        return FakeLocator(self, action=name)


def test_synthetic_dom_journey_uses_local_page_and_stable_roles() -> None:
    page = FakePage()
    result = asyncio.run(SyntheticTicketScenario(page).simulate_general_reservation())
    assert result is SimulationOutcome.RESERVED_IN_SIMULATOR
    assert page.stage == "simulated_reserved"
    assert page.actions == [step.action for step in STEPS]


def test_synthetic_dom_stage_tampering_fails_before_clicks() -> None:
    page = FakePage(tamper=True)
    with pytest.raises(SyntheticFlowError, match="unexpected local simulation stage"):
        asyncio.run(SyntheticTicketScenario(page).simulate_general_reservation())
    assert page.actions == []


@pytest.mark.parametrize("timeout", [-1, 0, 999, 15_001, 99_999])
def test_reject_unbounded_browser_timeouts(timeout: int) -> None:
    with pytest.raises(ValueError, match="timeout"):
        SyntheticTicketScenario(FakePage(), timeout_ms=timeout)


def test_browser_error_does_not_emit_success_notice() -> None:
    class UnavailableBrowser:
        async def simulate_general_reservation(self) -> SimulationOutcome:
            raise TimeoutError("synthetic_timeout")

    store, notices = FakeIntentStore(), FakeNotifications()
    workflow = SyntheticBrowserWorkflow(
        intents=store, browser=UnavailableBrowser(), notifications=notices
    )
    with pytest.raises(TimeoutError):
        asyncio.run(workflow.run(TicketIntent("synthetic-member", "synthetic-match")))
    assert len(store.requests) == 1
    assert notices.notices == []


def test_empty_request_identifier_fails_before_browser() -> None:
    class BrokenStore:
        def ensure_ticket_intent(self, intent: TicketIntent) -> str:
            return ""

    browser, notices = FakeBrowser(), FakeNotifications()
    workflow = SyntheticBrowserWorkflow(
        intents=BrokenStore(), browser=browser, notifications=notices
    )
    with pytest.raises(ValueError, match="empty request_id"):
        asyncio.run(workflow.run(TicketIntent("synthetic-member", "synthetic-match")))
    assert browser.calls == 0 and notices.notices == []


def test_distinct_members_have_distinct_local_intents() -> None:
    store, browser, notices = FakeIntentStore(), FakeBrowser(), FakeNotifications()
    workflow = SyntheticBrowserWorkflow(intents=store, browser=browser, notifications=notices)
    first = asyncio.run(workflow.run(TicketIntent("synthetic-a", "synthetic-match")))
    second = asyncio.run(workflow.run(TicketIntent("synthetic-b", "synthetic-match")))
    assert first.request_id != second.request_id
    assert len(store.requests) == 2


def test_notifications_contain_only_opaque_metadata() -> None:
    store, browser, notices = FakeIntentStore(), FakeBrowser(), FakeNotifications()
    workflow = SyntheticBrowserWorkflow(intents=store, browser=browser, notifications=notices)
    asyncio.run(workflow.run(TicketIntent("synthetic-a", "synthetic-match")))
    notice = notices.notices[0]
    assert tuple(notice.__dataclass_fields__) == ("request_id", "member_id", "event_id", "outcome")


@pytest.mark.parametrize("tamper,exit_code", [(False, 0), (True, 1)])
def test_optional_chromium_script_closes_browser_context_on_all_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tamper: bool,
    exit_code: int,
) -> None:
    """Simulate Playwright itself; actual Chromium remains a separate smoke."""
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_synthetic_ticket_flow.py"
    run = run_path(str(script_path))["run"]

    class FakeContext:
        def __init__(self) -> None:
            self.closed = False
            self.route_pattern: str | None = None

        async def route(
            self, pattern: str, callback: Callable[[FakeRoute], Awaitable[None]]
        ) -> None:
            self.route_pattern = pattern
            route = FakeRoute()
            await callback(route)
            assert route.aborted

        async def new_page(self) -> FakePage:
            return FakePage(tamper=tamper)

        async def close(self) -> None:
            self.closed = True

    class FakeRoute:
        def __init__(self) -> None:
            self.aborted = False

        async def abort(self) -> None:
            self.aborted = True

    context = FakeContext()

    class Browser:
        def __init__(self) -> None:
            self.closed = False

        async def new_context(self, *, service_workers: str, accept_downloads: bool) -> FakeContext:
            assert service_workers == "block" and not accept_downloads
            return context

        async def close(self) -> None:
            self.closed = True

    browser = Browser()

    class Chromium:
        async def launch(self, *, headless: bool, timeout: int, args: list[str]) -> Browser:
            assert headless and timeout == 15_000
            assert "--disable-background-networking" in args
            return browser

    class API:
        chromium = Chromium()

    class PlaywrightContext:
        async def __aenter__(self) -> API:
            return API()

        async def __aexit__(self, *_args: object) -> None:
            pass

    fake_package = ModuleType("playwright")
    fake_package.__path__ = []  # type: ignore[attr-defined]
    fake_async_api = ModuleType("playwright.async_api")
    fake_async_api.async_playwright = PlaywrightContext  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", fake_package)
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_async_api)

    assert asyncio.run(run()) == exit_code
    assert context.closed and browser.closed
    assert context.route_pattern == "**/*"
    output = capsys.readouterr()
    if not tamper:
        assert json.loads(output.out) == {
            "mode": "synthetic_only",
            "result": "reserved_in_simulator",
            "notices": 1,
        }
    else:
        assert "SyntheticFlowError" in output.err
        assert "http" not in output.err
