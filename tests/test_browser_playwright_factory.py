"""The optional Chromium factory has no inputs, egress or persistent session."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from types import ModuleType

import pytest

from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.browser.on_demand import OnDemandSyntheticBrowser, WorkerBoundaryError
from boca_socios.browser.playwright_factory import isolated_playwright_page
from boca_socios.browser.synthetic import STEPS, SYNTHETIC_HTML, SyntheticFlowError


class FakeLocator:
    def __init__(self, page: FakePage, action: str | None = None) -> None:
        self._page = page
        self._action = action

    async def inner_text(self, *, timeout: float) -> str:
        assert timeout == 5_000
        return self._page.stage

    async def click(self, *, timeout: float) -> None:
        assert timeout == 5_000
        step = next((s for s in STEPS if s.before == self._page.stage), None)
        if step is None or step.action != self._action:
            raise SyntheticFlowError("invalid fixture action")
        self._page.stage = step.after
        self._page.actions.append(step.action)


class FakePage:
    def __init__(self, *, tamper: bool = False) -> None:
        self.tamper = tamper
        self.stage = "new"
        self.actions: list[str] = []

    async def set_content(self, html: str, *, wait_until: str, timeout: float) -> None:
        assert html == SYNTHETIC_HTML
        assert wait_until == "load" and timeout == 5_000
        self.stage = "corrupted" if self.tamper else "prequeue"

    def locator(self, selector: str) -> FakeLocator:
        assert selector == "#stage"
        return FakeLocator(self)

    def get_by_role(self, role: str, *, name: str) -> FakeLocator:
        assert role == "button"
        return FakeLocator(self, name)


class FakeRoute:
    def __init__(self) -> None:
        self.aborted = False

    async def abort(self) -> None:
        self.aborted = True


class FakeContext:
    def __init__(self, page: FakePage, *, fail_open: bool = False) -> None:
        self.page = page
        self.fail_open = fail_open
        self.closed = False
        self.all_requests_blocked = False

    async def route(self, pattern: str, callback: Callable[[FakeRoute], Awaitable[None]]) -> None:
        assert pattern == "**/*"
        route = FakeRoute()
        await callback(route)
        self.all_requests_blocked = route.aborted

    async def new_page(self) -> FakePage:
        if self.fail_open:
            raise RuntimeError("page_unavailable")
        return self.page

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.closed = False

    async def new_context(self, *, service_workers: str, accept_downloads: bool) -> FakeContext:
        assert service_workers == "block" and not accept_downloads
        return self.context

    async def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.launches = 0

    async def launch(
        self, *, headless: bool, chromium_sandbox: bool, timeout: int, args: list[str]
    ) -> FakeBrowser:
        assert headless and chromium_sandbox and timeout == 15_000
        assert args == ["--disable-background-networking"]
        self.launches += 1
        return self.browser


def install_fake_playwright(monkeypatch: pytest.MonkeyPatch, chromium: FakeChromium) -> None:
    class API:
        pass

    class AsyncPlaywright:
        async def __aenter__(self) -> API:
            api = API()
            api.chromium = chromium  # type: ignore[attr-defined]
            return api

        async def __aexit__(self, *_args: object) -> None:
            return None

    package = ModuleType("playwright")
    package.__path__ = []  # type: ignore[attr-defined]
    async_api = ModuleType("playwright.async_api")
    async_api.async_playwright = AsyncPlaywright  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api)


@pytest.mark.parametrize("tamper", [False, True])
def test_real_playwright_lifecycle_is_lazy_local_only_and_closes_on_both_paths(
    monkeypatch: pytest.MonkeyPatch, tamper: bool
) -> None:
    monkeypatch.setattr(
        "boca_socios.browser.playwright_factory.validate_worker_boundary", lambda: None
    )
    page = FakePage(tamper=tamper)
    context = FakeContext(page)
    browser = FakeBrowser(context)
    chromium = FakeChromium(browser)
    install_fake_playwright(monkeypatch, chromium)

    async def exercise() -> None:
        runner = OnDemandSyntheticBrowser(isolated_playwright_page, boundary_check=lambda: None)
        assert chromium.launches == 0
        if tamper:
            with pytest.raises(SyntheticFlowError, match="unexpected local simulation"):
                await runner.simulate_general_reservation()
        else:
            assert (
                await runner.simulate_general_reservation()
                is SimulationOutcome.RESERVED_IN_SIMULATOR
            )
            assert page.actions == [step.action for step in STEPS]
        await runner.close()

    asyncio.run(exercise())
    assert chromium.launches == 1
    assert context.all_requests_blocked
    assert context.closed and browser.closed


def test_browser_context_failure_still_closes_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "boca_socios.browser.playwright_factory.validate_worker_boundary", lambda: None
    )
    context = FakeContext(FakePage(), fail_open=True)
    browser = FakeBrowser(context)
    install_fake_playwright(monkeypatch, FakeChromium(browser))

    async def exercise() -> None:
        runner = OnDemandSyntheticBrowser(isolated_playwright_page, boundary_check=lambda: None)
        with pytest.raises(RuntimeError, match="page_unavailable"):
            await runner.simulate_general_reservation()
        await runner.close()

    asyncio.run(exercise())
    assert context.closed and browser.closed


def test_refuses_unverified_worker_before_playwright_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "boca_socios.browser.playwright_factory.validate_worker_boundary",
        lambda: (_ for _ in ()).throw(WorkerBoundaryError("identity_unverified")),
    )
    with pytest.raises(WorkerBoundaryError, match="identity_unverified"):
        asyncio.run(isolated_playwright_page().__aenter__())
