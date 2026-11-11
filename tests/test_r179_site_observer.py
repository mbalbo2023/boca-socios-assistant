"""Single-document sandbox SITE_URL inspection using fakes, never live traffic."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest

from boca_socios.browser import site_observer
from boca_socios.browser.ipc_protocol import SyntheticIPCError
from boca_socios.browser.ipc_server import SiteObservationStatus


@dataclass
class FakeRequest:
    url: str
    method: str = "GET"
    resource_type: str = "document"
    navigation: bool = True

    def is_navigation_request(self) -> bool:
        return self.navigation


class FakeRoute:
    def __init__(self, request: FakeRequest) -> None:
        self.request = request
        self.actions: list[str] = []

    async def continue_(self) -> None:
        self.actions.append("GET")

    async def abort(self) -> None:
        self.actions.append("ABORT")


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        (FakeRequest("https://sandbox.example.test/"), "GET"),
        (FakeRequest("https://sandbox.example.test/api", method="POST"), "ABORT"),
        (FakeRequest("https://prod.example.com/"), "ABORT"),
        (
            FakeRequest("https://sandbox.example.test/", resource_type="script", navigation=False),
            "ABORT",
        ),
        (FakeRequest("https://sandbox.example.test/", method="PUT"), "ABORT"),
    ],
)
def test_route_allows_only_exact_get_document_once(candidate: FakeRequest, expected: str) -> None:
    async def exercise() -> None:
        guard = site_observer.single_document_get_guard("https://sandbox.example.test/")
        route = FakeRoute(candidate)
        await guard(route)
        assert route.actions == [expected]
        again = FakeRoute(FakeRequest("https://sandbox.example.test/"))
        await guard(again)
        assert again.actions == (["ABORT"] if expected == "GET" else ["GET"])
        redirected = FakeRoute(FakeRequest("https://sandbox.example.test/redirect"))
        await guard(redirected)
        assert redirected.actions == ["ABORT"]

    asyncio.run(exercise())


def test_browser_root_slash_normalization_allows_no_additional_document() -> None:
    async def exercise() -> None:
        guard = site_observer.single_document_get_guard("https://sandbox.example.test")
        root = FakeRoute(FakeRequest("https://sandbox.example.test/"))
        await guard(root)
        assert root.actions == ["GET"]
        reload = FakeRoute(FakeRequest("https://sandbox.example.test/"))
        await guard(reload)
        assert reload.actions == ["ABORT"]

    asyncio.run(exercise())


def test_plain_chromium_has_no_stealth_or_script_and_closes_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        steps: list[str] = []
        events: list[str] = []
        monkeypatch.setattr(site_observer, "emit_chromium_event", events.append)

        class FakeContext:
            async def route(self, pattern: str, handler: object) -> None:
                assert pattern == "**/*" and callable(handler)
                steps.append("route")
                real = FakeRoute(FakeRequest("https://sandbox.example.test/"))
                await handler(real)
                assert real.actions == ["GET"]

            async def new_page(self) -> FakePage:
                steps.append("page")
                return FakePage(200)

            async def close(self) -> None:
                steps.append("context_closed")

        class FakeBrowser:
            async def new_context(self, **options: object) -> FakeContext:
                assert options == {
                    "java_script_enabled": False,
                    "service_workers": "block",
                    "accept_downloads": False,
                    "ignore_https_errors": False,
                }
                steps.append("context")
                return FakeContext()

            async def close(self) -> None:
                steps.append("browser_closed")

        class FakeChromium:
            async def launch(self, **options: object) -> FakeBrowser:
                assert options == {
                    "headless": True,
                    "chromium_sandbox": True,
                    "timeout": 12000,
                    "args": ["--disable-background-networking"],
                }
                steps.append("browser")
                return FakeBrowser()

        class FakePlaywright:
            chromium = FakeChromium()

        @asynccontextmanager
        async def fake_playwright() -> AsyncIterator[FakePlaywright]:
            yield FakePlaywright()

        async with site_observer.isolated_site_readonly_page(
            "https://sandbox.example.test/",
            playwright_factory=fake_playwright,
            boundary_check=lambda: None,
        ) as page:
            assert isinstance(page, FakePage)
        assert steps == ["browser", "context", "route", "page", "context_closed", "browser_closed"]
        assert events == [
            "launch_requested",
            "launched",
            "context_ready",
            "context_closed",
            "browser_closed",
        ]

    asyncio.run(exercise())


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status


class FakePage:
    def __init__(self, status: int | None) -> None:
        self.status = status
        self.seen: list[tuple[str, str, int]] = []

    async def goto(self, url: str, *, wait_until: str, timeout: int) -> FakeResponse | None:
        self.seen.append((url, wait_until, timeout))
        return FakeResponse(self.status) if self.status is not None else None


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (200, "HTTP_OK"),
        (204, "HTTP_OK"),
        (302, "HTTP_NON_OK"),
        (403, "HTTP_NON_OK"),
        (503, "HTTP_NON_OK"),
    ],
)
def test_injected_page_returns_only_http_category_and_closes(status: int, outcome: str) -> None:
    async def exercise() -> None:
        page = FakePage(status)
        visits: list[str] = []
        closed: list[bool] = []

        @asynccontextmanager
        async def fake_pages(url: str) -> AsyncIterator[FakePage]:
            visits.append(url)
            try:
                yield page
            finally:
                closed.append(True)

        executor = site_observer.SiteReadOnlyExecutor(
            "https://sandbox.example.test/", pages=fake_pages, boundary_check=lambda: None
        )
        assert await executor.observe_site() is getattr(SiteObservationStatus, outcome)
        assert visits == ["https://sandbox.example.test/"]
        assert page.seen == [("https://sandbox.example.test/", "domcontentloaded", 12000)]
        assert closed == [True]
        await executor.close()
        with pytest.raises(SyntheticIPCError, match="site_observer_stopped"):
            await executor.observe_site()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "https://user:secret@sandbox.example.test/", "http://169.254.169.254/"],
)
def test_site_observer_refuses_invalid_or_metadata_url(url: str) -> None:
    with pytest.raises(ValueError):
        site_observer.SiteReadOnlyExecutor(url)


def test_site_observer_stop_rejects_late_http_ack() -> None:
    async def exercise() -> None:
        started = asyncio.Event()
        close_seen: list[bool] = []

        class SlowPage:
            async def goto(self, _url: str, *, wait_until: str, timeout: int) -> FakeResponse:
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    return FakeResponse(200)
                return FakeResponse(200)

        @asynccontextmanager
        async def fake_pages(_url: str) -> AsyncIterator[SlowPage]:
            try:
                yield SlowPage()
            finally:
                close_seen.append(True)

        executor = site_observer.SiteReadOnlyExecutor(
            "https://sandbox.example.test/", pages=fake_pages, boundary_check=lambda: None
        )
        pending = asyncio.create_task(executor.observe_site())
        await asyncio.wait_for(started.wait(), 1)
        await executor.close()
        with pytest.raises(SyntheticIPCError, match="site_observer_stopped"):
            await pending
        assert close_seen == [True]

    asyncio.run(exercise())


def test_site_observer_timeout_is_redacted_and_closes() -> None:
    async def exercise() -> None:
        closed: list[bool] = []

        class HungPage:
            async def goto(self, _url: str, *, wait_until: str, timeout: int) -> FakeResponse:
                await asyncio.Event().wait()
                return FakeResponse(200)

        @asynccontextmanager
        async def fake_pages(_url: str) -> AsyncIterator[HungPage]:
            try:
                yield HungPage()
            finally:
                closed.append(True)

        executor = site_observer.SiteReadOnlyExecutor(
            "https://sandbox.example.test/",
            pages=fake_pages,
            timeout_seconds=0.03,
            boundary_check=lambda: None,
        )
        with pytest.raises(SyntheticIPCError, match="site_observer_timeout"):
            await executor.observe_site()
        assert closed == [True]
        await executor.close()

    asyncio.run(exercise())


def test_site_observer_unverified_teardown_poisoned() -> None:
    async def exercise() -> None:
        @asynccontextmanager
        async def broken_pages(_url: str) -> AsyncIterator[FakePage]:
            yield FakePage(200)
            raise SyntheticIPCError("site_observer_teardown_unverified")

        executor = site_observer.SiteReadOnlyExecutor(
            "https://sandbox.example.test/", pages=broken_pages, boundary_check=lambda: None
        )
        with pytest.raises(SyntheticIPCError, match="site_observer_teardown_unverified"):
            await executor.observe_site()
        with pytest.raises(SyntheticIPCError, match="site_observer_stopped"):
            await executor.observe_site()
        with pytest.raises(SyntheticIPCError, match="site_observer_teardown_unverified"):
            await executor.close()

    asyncio.run(exercise())
