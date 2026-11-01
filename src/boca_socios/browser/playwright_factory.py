"""Opt-in Chromium page factory strictly for the embedded fake DOM journey.

Importing this module does not start Playwright or Chromium. Call it only from
an independently isolated UID 10002, network-none, capped browser container;
it is never a substitute for OS-level no-egress enforcement. Nothing here
accepts a URL, account, cookie, live queue position or payment instruction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol, cast

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
        browser = await api.chromium.launch(
            headless=True,
            timeout=15_000,
            args=["--disable-background-networking"],
        )
        try:
            context = await browser.new_context(
                service_workers="block",
                accept_downloads=False,
            )
            try:

                async def deny_every_request(route: _BlockedRoute) -> None:
                    await route.abort()

                # set_content() has no external assets. This route is a
                # second defense against later DOM drift, not an OS firewall.
                await context.route("**/*", deny_every_request)
                yield cast("PagePort", await context.new_page())
            finally:
                await context.close()
        finally:
            await browser.close()
