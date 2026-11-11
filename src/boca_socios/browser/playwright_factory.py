"""Opt-in Chromium page factory strictly for the embedded fake DOM journey.

Importing this module does not start Playwright or Chromium. Call it only from
an independently isolated UID 10002, Boca-only-egress, capped browser container;
it is never a substitute for OS-level Boca network isolation. Nothing here
accepts a URL, account, cookie, live queue position or payment instruction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol, cast

from boca_socios.browser.activity_events import emit_chromium_event
from boca_socios.browser.on_demand import validate_worker_boundary
from boca_socios.browser.synthetic import PagePort


class _BlockedRoute(Protocol):
    async def abort(self) -> None: ...


@asynccontextmanager
async def isolated_playwright_page() -> AsyncIterator[PagePort]:
    """Create one fresh about:blank context with *all* page requests denied.

    The caller must drive only ``SyntheticTicketScenario`` on this page. No
    browser is started until an active fake command enters this context.
    Browser and context are disposed of on success, failure or cancellation.
    The host must kill the worker on uncooperative teardown.
    """
    validate_worker_boundary()

    # The optional browser image pins Playwright; the controller runtime must
    # remain installable and importable without that heavy dependency.
    from playwright.async_api import async_playwright  # type: ignore[import-not-found]

    async with async_playwright() as api:
        emit_chromium_event("launch_requested")
        try:
            browser = await api.chromium.launch(
                headless=True,
                chromium_sandbox=True,
                timeout=15_000,
                args=["--disable-background-networking"],
            )
        except BaseException:
            emit_chromium_event("operation_failed")
            raise
        emit_chromium_event("launched")
        try:
            context = await browser.new_context(
                service_workers="block",
                accept_downloads=False,
            )
            emit_chromium_event("context_ready")
            try:

                async def deny_every_request(route: _BlockedRoute) -> None:
                    await route.abort()

                # set_content() has no external assets. This route is a
                # second defense against later DOM drift, not an OS firewall.
                await context.route("**/*", deny_every_request)
                page = await context.new_page()
                emit_chromium_event("page_ready")
                yield cast("PagePort", page)
            finally:
                await context.close()
                emit_chromium_event("context_closed")
        except BaseException:
            emit_chromium_event("operation_failed")
            raise
        finally:
            try:
                await browser.close()
            except BaseException:
                emit_chromium_event("operation_failed")
                raise
            else:
                emit_chromium_event("browser_closed")
