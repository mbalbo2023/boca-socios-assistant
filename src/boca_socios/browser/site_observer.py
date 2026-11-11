"""Opt-in, one-document HTTP(S) observation for a reviewed sandbox SITE_URL.

This is NOT the owner legacy navigation engine: no stealth flags, Queue-it
token/cookie inspection, background swarm, clicks, form submits, downloads or
provider actions. The exact destination is supplied by the existing Boca-only
runtime URL mount, never by an IPC request. No Playwright import/network occurs
until the explicit PROBE_SITE command reaches this instance.

An HTTP GET can have side effects on a misconfigured remote server. The owner
must select a sandbox endpoint; this module never claims a real-site action.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from math import isfinite
from typing import Protocol, cast

from boca_socios.browser.activity_events import emit_chromium_event
from boca_socios.browser.ipc_protocol import SyntheticIPCError
from boca_socios.browser.ipc_server import SiteObservationStatus
from boca_socios.browser.offline_fixture import _bounded_close
from boca_socios.browser.site_url_runtime import require_site_url
from boca_socios.browser.worker_health import validate_worker_boundary


class _Request(Protocol):
    url: str
    method: str
    resource_type: str

    def is_navigation_request(self) -> bool: ...


class _Route(Protocol):
    request: _Request

    async def continue_(self) -> None: ...

    async def abort(self) -> None: ...


class _Response(Protocol):
    status: int


class _Page(Protocol):
    async def goto(self, url: str, *, wait_until: str, timeout: int) -> _Response | None: ...


class _Context(Protocol):
    async def route(self, pattern: str, handler: Callable[[_Route], Awaitable[None]]) -> None: ...

    async def new_page(self) -> _Page: ...

    async def close(self) -> None: ...


class _Browser(Protocol):
    async def new_context(self, **options: object) -> _Context: ...

    async def close(self) -> None: ...


class _Chromium(Protocol):
    async def launch(self, **options: object) -> _Browser: ...


class _Playwright(Protocol):
    chromium: _Chromium


SitePageFactory = Callable[[str], AbstractAsyncContextManager[_Page]]
PlaywrightFactory = Callable[[], AbstractAsyncContextManager[_Playwright]]


def _default_playwright() -> AbstractAsyncContextManager[_Playwright]:
    from playwright.async_api import async_playwright  # type: ignore[import-not-found]

    return cast("AbstractAsyncContextManager[_Playwright]", async_playwright())


def single_document_get_guard(site_url: str) -> Callable[[_Route], Awaitable[None]]:
    """One exact document GET. Deny reload, redirect, POST and subresources."""
    expected = require_site_url(site_url)
    # Chromium adds the root slash to a bare HTTP(S) authority. This is only
    # syntactic normalization of the *same* path, never an open redirect.
    if expected.split("://", 1)[1].find("/") < 0:
        expected += "/"
    used = False

    async def handle(route: _Route) -> None:
        nonlocal used
        request = route.request
        if (
            not used
            and request.url == expected
            and request.method == "GET"
            and request.resource_type == "document"
            and request.is_navigation_request()
        ):
            used = True  # Set before await to deny concurrent second requests.
            await route.continue_()
        else:
            await route.abort()

    return handle


async def _close_site_resource(resource: _Context | _Browser) -> None:
    # Reuse the pre-existing bounded Chromium teardown, not a second motor.
    try:
        await _bounded_close(resource, 3.0)
    except SyntheticIPCError:
        raise SyntheticIPCError("site_observer_teardown_unverified") from None


@asynccontextmanager
async def isolated_site_readonly_page(
    site_url: str,
    *,
    playwright_factory: PlaywrightFactory | None = None,
    boundary_check: Callable[[], None] = validate_worker_boundary,
) -> AsyncIterator[_Page]:
    """Launch single ordinary Chromium context with no active page scripting.

    `route` is registered before opening the page; only the exact reviewed
    destination's first navigation GET can leave the browser context.
    """
    destination = require_site_url(site_url)
    boundary_check()
    factory = _default_playwright if playwright_factory is None else playwright_factory
    emit_chromium_event("launch_requested")
    try:
        async with factory() as api:
            browser = await api.chromium.launch(
                headless=True,
                chromium_sandbox=True,
                timeout=12_000,
                args=["--disable-background-networking"],
            )
            emit_chromium_event("launched")
            try:
                context = await browser.new_context(
                    java_script_enabled=False,
                    service_workers="block",
                    accept_downloads=False,
                    ignore_https_errors=False,
                )
                emit_chromium_event("context_ready")
                try:
                    await context.route("**/*", single_document_get_guard(destination))
                    page = await context.new_page()
                    # Existing dashboard label for `page_ready` claims that
                    # *synthetic* HTML was prepared; that would misdescribe a
                    # live sandbox GET. Keep only truthful lifecycle stages.
                    yield page
                finally:
                    await _close_site_resource(context)
                    emit_chromium_event("context_closed")
            finally:
                await _close_site_resource(browser)
                emit_chromium_event("browser_closed")
    except BaseException:
        emit_chromium_event("operation_failed")
        raise


class SiteReadOnlyExecutor:
    """Single-flight observer. No method implements a reservation contract."""

    def __init__(
        self,
        site_url: str,
        *,
        pages: SitePageFactory = isolated_site_readonly_page,
        boundary_check: Callable[[], None] = validate_worker_boundary,
        timeout_seconds: float = 15.0,
        teardown_seconds: float = 4.0,
    ) -> None:
        if (
            type(timeout_seconds) not in (float, int)
            or not isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 15.0
            or type(teardown_seconds) not in (float, int)
            or not isfinite(teardown_seconds)
            or not 0 < teardown_seconds <= 5.0
        ):
            raise ValueError("site observer timeout unverified")
        self._site_url = require_site_url(site_url)
        self._pages = pages
        self._check = boundary_check
        self._timeout = float(timeout_seconds)
        self._teardown = float(teardown_seconds)
        self._active: asyncio.Task[SiteObservationStatus] | None = None
        self._closed = False
        self._poisoned = False

    async def observe_site(self) -> SiteObservationStatus:
        if self._closed or self._poisoned:
            raise SyntheticIPCError("site_observer_stopped")
        if self._active is not None:
            raise SyntheticIPCError("site_observer_busy")
        self._check()
        active = asyncio.current_task()
        if active is None:
            raise SyntheticIPCError("site_observer_loop_unverified")
        self._active = active
        try:
            async with asyncio.timeout(self._timeout) as deadline:
                async with self._pages(self._site_url) as page:
                    response = await page.goto(
                        self._site_url, wait_until="domcontentloaded", timeout=12_000
                    )
                if self._closed or self._poisoned or active.cancelling() or deadline.expired():
                    raise SyntheticIPCError("site_observer_stopped")
                status = response.status if response is not None else None
                if type(status) is not int or not 200 <= status <= 599:
                    raise SyntheticIPCError("site_observer_navigation_failed")
                if status < 300:
                    return SiteObservationStatus.HTTP_OK
                return SiteObservationStatus.HTTP_NON_OK
        except TimeoutError:
            raise SyntheticIPCError("site_observer_timeout") from None
        except SyntheticIPCError as exc:
            if str(exc) == "site_observer_teardown_unverified":
                self._poisoned = True
            raise
        except Exception:
            raise SyntheticIPCError("site_observer_navigation_failed") from None
        finally:
            self._active = None

    async def close(self) -> None:
        self._closed = True
        active = self._active
        if active is not None and not active.done() and active is not asyncio.current_task():
            active.cancel()
            _, pending = await asyncio.wait({active}, timeout=self._teardown)
            if pending:
                self._poisoned = True
        if self._poisoned:
            raise SyntheticIPCError("site_observer_teardown_unverified")
