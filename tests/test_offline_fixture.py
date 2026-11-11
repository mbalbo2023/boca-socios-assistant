"""Fixed fake DOM execution; no real browser, sockets, third-party URLs or credentials."""

from __future__ import annotations

import asyncio
import importlib
import subprocess
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest

from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.browser.ipc_protocol import SyntheticIPCError


def fixture_module() -> Any:
    return importlib.import_module("boca_socios.browser.offline_fixture")


class FakeRoute:
    def __init__(self) -> None:
        self.aborted = False

    async def abort(self) -> None:
        self.aborted = True


class FakePage:
    def __init__(self) -> None:
        self.goto_calls: list[str] = []
        self.html = ""
        self.phase = "new"
        self.clicked = False
        self.page_routes: list[tuple[str, Callable[..., object]]] = []
        self.click_started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def goto(self, url: str, *, timeout: int) -> None:
        assert timeout == 5_000
        self.goto_calls.append(url)

    async def route(self, pattern: str, handler: Callable[..., object]) -> None:
        self.page_routes.append((pattern, handler))

    async def set_content(self, html: str, *, wait_until: str, timeout: int) -> None:
        assert wait_until == "load" and timeout == 5_000
        self.html = html
        self.phase = "ready"

    def locator(self, selector: str) -> FakePage:
        assert selector == "#fixture-stage"
        return self

    def get_by_role(self, role: str, *, name: str) -> FakePage:
        assert (role, name) == ("button", "Simular")
        return self

    async def inner_text(self, *, timeout: int) -> str:
        assert timeout == 5_000
        return self.phase

    async def click(self, *, timeout: int) -> None:
        assert timeout == 5_000
        self.click_started.set()
        await self.release.wait()
        self.clicked = True
        self.phase = "fixture_complete"


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.options: dict[str, object] = {}
        self.context_routes: list[tuple[str, Callable[..., object]]] = []
        self.closed = False

    async def route(self, pattern: str, handler: Callable[..., object]) -> None:
        self.context_routes.append((pattern, handler))

    async def new_page(self) -> FakePage:
        return self.page

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.closed = False
        self.options: dict[str, object] = {}

    async def new_context(self, **options: object) -> FakeContext:
        self.context.options = options
        return self.context

    async def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser

    async def launch(self, **options: object) -> FakeBrowser:
        self.browser.options = options
        return self.browser


class FakePlaywright:
    def __init__(self, chromium: FakeChromium) -> None:
        self.chromium = chromium


def test_import_and_constructor_do_not_load_owner_engines_or_accept_a_destination() -> None:
    module = fixture_module()
    clean_import = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import boca_socios.browser.offline_fixture\n"
                "import sys\n"
                "assert all(name not in sys.modules for name in ("
                "'boca_socios.browser.synthetic',"
                "'boca_socios.browser.ipc_worker',"
                "'boca_socios.browser.on_demand',"
                "'boca_socios.browser.playwright_factory'))"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert clean_import.returncode == 0, clean_import.stderr
    module.OfflineFixtureExecutor(boundary_check=lambda: None)
    with pytest.raises(TypeError):
        module.OfflineFixtureExecutor("https://example.invalid")


def test_fake_dom_is_literal_about_blank_and_requires_one_local_button_click() -> None:
    module = fixture_module()
    page = FakePage()

    async def exercise() -> None:
        outcome = await module.run_fixture_dom(page)
        assert outcome is SimulationOutcome.RESERVED_IN_SIMULATOR

    asyncio.run(exercise())
    assert page.goto_calls == ["about:blank"]
    assert page.clicked and page.phase == "fixture_complete"
    assert "<!doctype html>" in page.html.lower()
    assert "#fixture-stage" not in page.html  # The selector is for code, not HTML text.
    assert 'id="fixture-stage"' in page.html
    assert "https://" not in page.html and "http://" not in page.html
    assert "queue" not in page.html.lower() and "cookie" not in page.html.lower()


def test_fake_dom_wrong_final_state_cannot_claim_simulated_success() -> None:
    module = fixture_module()

    class WrongPage(FakePage):
        async def click(self, *, timeout: int) -> None:
            self.clicked = True
            self.phase = "not_completed"

    with pytest.raises(SyntheticIPCError, match="offline_fixture_dom_unverified"):
        asyncio.run(module.run_fixture_dom(WrongPage()))


def test_page_and_context_routes_abort_every_request_and_resources_close() -> None:
    module = fixture_module()
    page = FakePage()
    context = FakeContext(page)
    browser = FakeBrowser(context)

    @asynccontextmanager
    async def fake_playwright() -> AsyncIterator[FakePlaywright]:
        yield FakePlaywright(FakeChromium(browser))

    async def exercise() -> None:
        async with module.isolated_offline_fixture_page(
            playwright_factory=fake_playwright, boundary_check=lambda: None
        ) as rendered:
            assert rendered is page
            assert context.options["offline"] is True
            assert context.options["service_workers"] == "block"
            assert context.options["accept_downloads"] is False
            assert browser.options["chromium_sandbox"] is True
            assert browser.options["headless"] is True
            for registered in (context.context_routes, page.page_routes):
                assert len(registered) == 1
                pattern, callback = registered[0]
                assert pattern == "**/*"
                attempt = FakeRoute()
                await callback(attempt)
                assert attempt.aborted

    asyncio.run(exercise())
    assert context.closed and browser.closed


def test_offline_fixture_reports_only_fixed_browser_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    module = fixture_module()
    page = FakePage()
    context = FakeContext(page)
    browser = FakeBrowser(context)
    stages: list[str] = []
    monkeypatch.setattr(module, "emit_chromium_event", stages.append, raising=False)

    @asynccontextmanager
    async def fake_playwright() -> AsyncIterator[FakePlaywright]:
        yield FakePlaywright(FakeChromium(browser))

    async def exercise() -> None:
        async with module.isolated_offline_fixture_page(
            playwright_factory=fake_playwright, boundary_check=lambda: None
        ) as rendered:
            assert rendered is page

    asyncio.run(exercise())
    assert stages == [
        "launch_requested",
        "launched",
        "context_ready",
        "page_ready",
        "context_closed",
        "browser_closed",
    ]


def test_route_setup_failure_closes_context_and_browser_without_success() -> None:
    module = fixture_module()

    class BrokenPage(FakePage):
        async def route(self, pattern: str, handler: Callable[..., object]) -> None:
            raise RuntimeError("cannot install page abort handler")

    context = FakeContext(BrokenPage())
    browser = FakeBrowser(context)

    @asynccontextmanager
    async def fake_playwright() -> AsyncIterator[FakePlaywright]:
        yield FakePlaywright(FakeChromium(browser))

    async def exercise() -> None:
        with pytest.raises(RuntimeError, match="cannot install page abort handler"):
            async with module.isolated_offline_fixture_page(
                playwright_factory=fake_playwright, boundary_check=lambda: None
            ):
                raise AssertionError("no unsafe page may be yielded")

    asyncio.run(exercise())
    assert context.closed and browser.closed


def test_context_teardown_timeout_is_no_go_even_after_successful_fake_dom() -> None:
    module = fixture_module()
    page = FakePage()

    class UnclosableContext(FakeContext):
        async def close(self) -> None:
            await asyncio.Event().wait()

    context = UnclosableContext(page)
    browser = FakeBrowser(context)

    @asynccontextmanager
    async def fake_playwright() -> AsyncIterator[FakePlaywright]:
        yield FakePlaywright(FakeChromium(browser))

    async def exercise() -> None:
        with pytest.raises(SyntheticIPCError, match="^offline_fixture_teardown_unverified$"):
            async with module.isolated_offline_fixture_page(
                playwright_factory=fake_playwright,
                boundary_check=lambda: None,
                close_seconds=0.02,
            ) as rendered:
                assert (
                    await module.run_fixture_dom(rendered)
                    is SimulationOutcome.RESERVED_IN_SIMULATOR
                )

    asyncio.run(exercise())
    assert browser.closed


def test_unverified_teardown_poison_is_reported_again_at_executor_stop() -> None:
    module = fixture_module()

    @asynccontextmanager
    async def pages() -> AsyncIterator[FakePage]:
        yield FakePage()
        raise SyntheticIPCError("offline_fixture_teardown_unverified")

    async def exercise() -> None:
        executor = module.OfflineFixtureExecutor(pages=pages, boundary_check=lambda: None)
        with pytest.raises(SyntheticIPCError, match="^offline_fixture_teardown_unverified$"):
            await executor.simulate_general_reservation()
        with pytest.raises(SyntheticIPCError, match="^offline_fixture_teardown_unverified$"):
            await executor.close()

    asyncio.run(exercise())


def test_playwright_close_exception_is_redacted_poison_and_browser_still_closes() -> None:
    module = fixture_module()

    class FailedContext(FakeContext):
        async def close(self) -> None:
            raise RuntimeError("private-context-close-error")

    context = FailedContext(FakePage())
    browser = FakeBrowser(context)

    @asynccontextmanager
    async def fake_playwright() -> AsyncIterator[FakePlaywright]:
        yield FakePlaywright(FakeChromium(browser))

    def pages() -> Any:
        return module.isolated_offline_fixture_page(
            playwright_factory=fake_playwright, boundary_check=lambda: None
        )

    async def exercise() -> None:
        executor = module.OfflineFixtureExecutor(pages=pages, boundary_check=lambda: None)
        with pytest.raises(SyntheticIPCError, match="^offline_fixture_teardown_unverified$"):
            await executor.simulate_general_reservation()
        with pytest.raises(SyntheticIPCError, match="^offline_fixture_teardown_unverified$"):
            await executor.close()

    asyncio.run(exercise())
    assert browser.closed


def test_executor_does_nothing_until_called_and_closes_injected_page() -> None:
    module = fixture_module()
    page = FakePage()
    opened = 0
    closed = False

    @asynccontextmanager
    async def pages() -> AsyncIterator[FakePage]:
        nonlocal opened, closed
        opened += 1
        try:
            yield page
        finally:
            closed = True

    async def exercise() -> None:
        executor = module.OfflineFixtureExecutor(pages=pages, boundary_check=lambda: None)
        assert opened == 0
        assert (
            await executor.simulate_general_reservation() is SimulationOutcome.RESERVED_IN_SIMULATOR
        )
        await executor.close()
        with pytest.raises(SyntheticIPCError, match="offline_fixture_stopped"):
            await executor.simulate_general_reservation()

    asyncio.run(exercise())
    assert opened == 1 and closed


def test_single_flight_refuses_duplicate_while_fake_dom_is_active() -> None:
    module = fixture_module()
    page = FakePage()
    page.release.clear()

    @asynccontextmanager
    async def pages() -> AsyncIterator[FakePage]:
        yield page

    async def exercise() -> None:
        executor = module.OfflineFixtureExecutor(pages=pages, boundary_check=lambda: None)
        active = asyncio.create_task(executor.simulate_general_reservation())
        try:
            await asyncio.wait_for(page.click_started.wait(), 1)
            with pytest.raises(SyntheticIPCError, match="offline_fixture_busy"):
                await executor.simulate_general_reservation()
        finally:
            page.release.set()
        assert await asyncio.wait_for(active, 1) is SimulationOutcome.RESERVED_IN_SIMULATOR
        await executor.close()

    asyncio.run(exercise())


def test_timeout_cancels_fake_dom_and_closes_page() -> None:
    module = fixture_module()
    page = FakePage()
    page.release.clear()
    closed = False

    @asynccontextmanager
    async def pages() -> AsyncIterator[FakePage]:
        nonlocal closed
        try:
            yield page
        finally:
            closed = True

    async def exercise() -> None:
        executor = module.OfflineFixtureExecutor(
            pages=pages, boundary_check=lambda: None, timeout_seconds=0.03
        )
        with pytest.raises(TimeoutError):
            await executor.simulate_general_reservation()
        assert closed
        await executor.close()

    asyncio.run(exercise())


def test_stop_fences_cancelled_or_cancellation_suppressing_fake_result() -> None:
    module = fixture_module()

    class StubbornPage(FakePage):
        async def click(self, *, timeout: int) -> None:
            self.click_started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.phase = "fixture_complete"  # Hostile fake swallows STOP.

    page = StubbornPage()
    page.release.clear()
    closed = False

    @asynccontextmanager
    async def pages() -> AsyncIterator[FakePage]:
        nonlocal closed
        try:
            yield page
        finally:
            closed = True

    async def exercise() -> None:
        executor = module.OfflineFixtureExecutor(pages=pages, boundary_check=lambda: None)
        active = asyncio.create_task(executor.simulate_general_reservation())
        await asyncio.wait_for(page.click_started.wait(), 1)
        await asyncio.wait_for(executor.close(), 1)
        with pytest.raises((SyntheticIPCError, asyncio.CancelledError)):
            await asyncio.wait_for(active, 1)
        assert closed

    asyncio.run(exercise())


def test_resistant_fake_is_poisoned_after_bounded_stop() -> None:
    module = fixture_module()

    class StubbornPage(FakePage):
        async def click(self, *, timeout: int) -> None:
            self.click_started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                await self.release.wait()  # Simulate a context that ignores STOP.
            self.phase = "fixture_complete"

    page = StubbornPage()
    page.release.clear()

    @asynccontextmanager
    async def pages() -> AsyncIterator[FakePage]:
        yield page

    async def exercise() -> None:
        executor = module.OfflineFixtureExecutor(
            pages=pages, boundary_check=lambda: None, teardown_seconds=0.02
        )
        active = asyncio.create_task(executor.simulate_general_reservation())
        await asyncio.wait_for(page.click_started.wait(), 1)
        try:
            with pytest.raises(SyntheticIPCError, match="^offline_fixture_teardown_unverified$"):
                await asyncio.wait_for(executor.close(), 1)
            assert executor._poisoned
        finally:
            page.release.set()
        with pytest.raises(SyntheticIPCError, match="offline_fixture_stopped"):
            await asyncio.wait_for(active, 1)

    asyncio.run(exercise())


def test_failed_chromium_open_does_not_claim_success() -> None:
    module = fixture_module()

    @asynccontextmanager
    async def broken_pages() -> AsyncIterator[FakePage]:
        raise RuntimeError("fixture-private-error-text")
        yield FakePage()

    async def exercise() -> None:
        executor = module.OfflineFixtureExecutor(pages=broken_pages, boundary_check=lambda: None)
        with pytest.raises(RuntimeError, match="fixture-private-error-text"):
            await executor.simulate_general_reservation()
        await executor.close()

    asyncio.run(exercise())


def test_smoke_requires_no_network_interfaces_except_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = fixture_module()
    started = False

    def forbidden_executor() -> None:
        nonlocal started
        started = True
        raise AssertionError("worker must not be launched with egress")

    monkeypatch.setattr(module, "OfflineFixtureExecutor", forbidden_executor)
    monkeypatch.setattr(module.socket, "if_nameindex", lambda: [(1, "lo"), (2, "eth0")])
    with pytest.raises(SyntheticIPCError, match="^offline_fixture_network_unverified$"):
        asyncio.run(module.run_smoke())
    assert not started


def test_smoke_on_network_none_uses_fixed_executor_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = fixture_module()
    monkeypatch.setattr(module.socket, "if_nameindex", lambda: [(1, "lo")])
    closed = False

    class FakeExecutor:
        async def simulate_general_reservation(self) -> SimulationOutcome:
            return SimulationOutcome.RESERVED_IN_SIMULATOR

        async def close(self) -> None:
            nonlocal closed
            closed = True

    monkeypatch.setattr(module, "OfflineFixtureExecutor", FakeExecutor)
    assert asyncio.run(module.run_smoke()) is SimulationOutcome.RESERVED_IN_SIMULATOR
    assert closed


def test_cli_is_opt_in_fixed_receipt_and_rejects_all_external_arguments(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = fixture_module()
    called = 0

    async def fake_smoke() -> SimulationOutcome:
        nonlocal called
        called += 1
        return SimulationOutcome.RESERVED_IN_SIMULATOR

    monkeypatch.setattr(module, "run_smoke", fake_smoke)
    for argv in ([], ["--url", "https://example.invalid"], ["--smoke", "--site-url=x"]):
        assert module.main(argv) == 2
        assert called == 0
    assert module.main(["--smoke"]) == 0
    assert called == 1
    output = capsys.readouterr()
    assert output.out == '{"mode":"offline_fixture_only","result":"reserved_in_simulator"}\n'
    assert "example.invalid" not in output.out + output.err
