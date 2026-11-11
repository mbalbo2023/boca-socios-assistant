"""One fixed, inert Chromium DOM fixture for the existing Boca synthetic IPC.

This module owns no URL, account, session, token or ticket action. It imports
none of the owner's navigation modules and cannot select a destination. The
sole positive outcome means *only* that this literal, invented local HTML
responded to one simulated click; it is not a Boca or Queue-it reservation.

Run the optional ``--smoke`` CLI only in the isolated UID10002 browser image,
with Docker ``--network none`` and bounded cgroups. Playwright route aborts and
context.offline are defense in depth, NOT a substitute for kernel isolation.
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from math import isfinite
from typing import Protocol, cast

from boca_socios.browser.activity_events import emit_chromium_event
from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.browser.ipc_protocol import SyntheticIPCError
from boca_socios.browser.worker_health import validate_worker_boundary

_HTML = """<!doctype html>
<html lang="es">
<head><meta charset="utf-8"><title>Ensayo local sin sitio externo</title></head>
<body>
  <h1>Ensayo local</h1>
  <p id="fixture-stage">ready</p>
  <button type="button" onclick="document.getElementById('fixture-stage').textContent='fixture_complete'">Simular</button>
</body></html>"""


class _Route(Protocol):
    async def abort(self) -> None: ...


class _Locator(Protocol):
    async def inner_text(self, *, timeout: int) -> str: ...

    async def click(self, *, timeout: int) -> None: ...


class _Page(Protocol):
    async def goto(self, url: str, *, timeout: int) -> None: ...

    async def set_content(self, html: str, *, wait_until: str, timeout: int) -> None: ...

    async def route(self, pattern: str, handler: Callable[[_Route], object]) -> None: ...

    def locator(self, selector: str) -> _Locator: ...

    def get_by_role(self, role: str, *, name: str) -> _Locator: ...


class _Closable(Protocol):
    async def close(self) -> None: ...


class _Context(_Closable, Protocol):
    async def route(self, pattern: str, handler: Callable[[_Route], object]) -> None: ...

    async def new_page(self) -> _Page: ...


class _Browser(_Closable, Protocol):
    async def new_context(self, **options: object) -> _Context: ...


class _Chromium(Protocol):
    async def launch(self, **options: object) -> _Browser: ...


class _Playwright(Protocol):
    chromium: _Chromium


PageFactory = Callable[[], AbstractAsyncContextManager[_Page]]
PlaywrightFactory = Callable[[], AbstractAsyncContextManager[_Playwright]]


def _default_playwright() -> AbstractAsyncContextManager[_Playwright]:
    # Deliberately lazy: module import and dormant worker never load Chromium.
    from playwright.async_api import async_playwright  # type: ignore[import-not-found]

    return cast("AbstractAsyncContextManager[_Playwright]", async_playwright())


async def _abort_every_request(route: _Route) -> None:
    await route.abort()


@asynccontextmanager
async def isolated_offline_fixture_page(
    *,
    playwright_factory: PlaywrightFactory | None = None,
    boundary_check: Callable[[], None] = validate_worker_boundary,
    close_seconds: float = 3.0,
) -> AsyncIterator[_Page]:
    """Launch a fresh offline context and deny ALL page/context requests.

    A failed or uncooperative close is never interpreted as a successful fake
    journey. The protected host must terminate the exact disposable worker on
    an unverified teardown; this function never touches Docker itself.
    """
    _seconds(close_seconds, 5.0)
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
                    offline=True,
                    service_workers="block",
                    accept_downloads=False,
                    java_script_enabled=True,
                )
                emit_chromium_event("context_ready")
                try:
                    await context.route("**/*", _abort_every_request)
                    page = await context.new_page()
                    await page.route("**/*", _abort_every_request)
                    emit_chromium_event("page_ready")
                    yield page
                finally:
                    await _bounded_close(context, close_seconds)
                    emit_chromium_event("context_closed")
            finally:
                await _bounded_close(browser, close_seconds)
                emit_chromium_event("browser_closed")
    except BaseException:
        # Fixed public activity category only; never log Playwright errors.
        emit_chromium_event("operation_failed")
        raise


async def _bounded_close(resource: _Closable, seconds: float) -> None:
    closing = asyncio.create_task(resource.close())
    closing.add_done_callback(_consume)
    try:
        finished, pending = await asyncio.wait({closing}, timeout=seconds)
    except asyncio.CancelledError:
        closing.cancel()
        raise SyntheticIPCError("offline_fixture_teardown_unverified") from None
    if pending:
        closing.cancel()
        raise SyntheticIPCError("offline_fixture_teardown_unverified")
    if finished:
        try:
            closing.result()
        except (Exception, asyncio.CancelledError):
            raise SyntheticIPCError("offline_fixture_teardown_unverified") from None


def _consume(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except (Exception, asyncio.CancelledError):
        # Never print browser paths, HTTP responses or Playwright exception text.
        return


async def run_fixture_dom(page: _Page) -> SimulationOutcome:
    """One invented local DOM transition; no URL or user data is accepted."""
    await page.goto("about:blank", timeout=5_000)
    await page.set_content(_HTML, wait_until="load", timeout=5_000)
    state = page.locator("#fixture-stage")
    if await state.inner_text(timeout=5_000) != "ready":
        raise SyntheticIPCError("offline_fixture_dom_unverified")
    await page.get_by_role("button", name="Simular").click(timeout=5_000)
    if await state.inner_text(timeout=5_000) != "fixture_complete":
        raise SyntheticIPCError("offline_fixture_dom_unverified")
    return SimulationOutcome.RESERVED_IN_SIMULATOR


def _seconds(value: float, maximum: float) -> float:
    if type(value) not in (float, int) or not isfinite(value) or not 0 < value <= maximum:
        raise ValueError("offline fixture timeout must be finite and bounded")
    return float(value)


class OfflineFixtureExecutor:
    """Demand-only, single-flight executor implementing the existing IPC port."""

    def __init__(
        self,
        *,
        pages: PageFactory = isolated_offline_fixture_page,
        boundary_check: Callable[[], None] = validate_worker_boundary,
        timeout_seconds: float = 15.0,
        teardown_seconds: float = 4.0,
    ) -> None:
        self._pages = pages
        self._check = boundary_check
        self._timeout = _seconds(timeout_seconds, 15.0)
        self._teardown = _seconds(teardown_seconds, 5.0)
        self._active: asyncio.Task[SimulationOutcome] | None = None
        self._closed = False
        self._poisoned = False

    async def simulate_general_reservation(self) -> SimulationOutcome:
        if self._closed or self._poisoned:
            raise SyntheticIPCError("offline_fixture_stopped")
        if self._active is not None:
            raise SyntheticIPCError("offline_fixture_busy")
        self._check()
        active = asyncio.current_task()
        if active is None:
            raise SyntheticIPCError("offline_fixture_loop_unverified")
        self._active = cast("asyncio.Task[SimulationOutcome]", active)
        try:
            async with asyncio.timeout(self._timeout) as deadline:
                async with self._pages() as page:
                    result = await run_fixture_dom(page)
                # Result acceptance comes *after* context/browser teardown.
                if (
                    self._closed
                    or self._poisoned
                    or active.cancelling()
                    or deadline.expired()
                    or result is not SimulationOutcome.RESERVED_IN_SIMULATOR
                ):
                    raise SyntheticIPCError("offline_fixture_stopped")
                return result
        except SyntheticIPCError as exc:
            if str(exc) == "offline_fixture_teardown_unverified":
                self._poisoned = True
            raise
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
            raise SyntheticIPCError("offline_fixture_teardown_unverified")


async def run_smoke() -> SimulationOutcome:
    """Callable only from an explicit offline browser-image CLI smoke."""
    _require_no_egress_namespace()
    executor = OfflineFixtureExecutor()
    try:
        return await executor.simulate_general_reservation()
    finally:
        await executor.close()


def _require_no_egress_namespace() -> None:
    """Fail closed unless the CLI sees only the Docker network-none loopback.

    This checks the namespace's interface names, not its routing table, and is
    defense in depth. The host must still enforce Docker ``--network none``.
    """
    try:
        interfaces = socket.if_nameindex()
    except OSError:
        raise SyntheticIPCError("offline_fixture_network_unverified") from None
    if len(interfaces) != 1 or interfaces[0][0] <= 0 or interfaces[0][1] != "lo":
        raise SyntheticIPCError("offline_fixture_network_unverified")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments != ["--smoke"]:
        print("BOCA_OFFLINE_FIXTURE state=NO_GO", file=sys.stderr)
        return 2
    try:
        outcome = asyncio.run(asyncio.wait_for(run_smoke(), timeout=25))
        if outcome is not SimulationOutcome.RESERVED_IN_SIMULATOR:
            raise SyntheticIPCError("offline_fixture_unverified")
    except (Exception, KeyboardInterrupt):
        print("BOCA_OFFLINE_FIXTURE state=NO_GO", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"mode": "offline_fixture_only", "result": "reserved_in_simulator"},
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
