"""Optional local-only Chromium smoke: no Boca, Queue-it, credentials or URLs.

Install the *pinned* Playwright package and Chromium on a dedicated lab machine
before running. The repository controller never imports this script.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Protocol, cast

from boca_socios.browser.contracts import (
    SimulationNotice,
    SimulationOutcome,
    SyntheticBrowserWorkflow,
)
from boca_socios.browser.synthetic import PagePort, SyntheticTicketScenario
from boca_socios.domain.policy import TicketIntent


class AbortRoutePort(Protocol):
    async def abort(self) -> None: ...


class DemoIntents:
    """Nonpersistent port for the one fixed fictitious member and event."""

    def ensure_ticket_intent(self, intent: TicketIntent) -> str:
        if (intent.member_id, intent.event_id) != ("synthetic-member", "synthetic-event"):
            raise ValueError("only the fixed fictitious identity is supported")
        return "synthetic-request-1"


class DemoNotifications:
    def __init__(self) -> None:
        self.notices: list[SimulationNotice] = []

    def publish_simulation_notice(self, notice: SimulationNotice) -> None:
        self.notices.append(notice)


class PageDriver:
    def __init__(self, page: PagePort) -> None:
        self._scenario = SyntheticTicketScenario(page)

    async def simulate_general_reservation(self) -> SimulationOutcome:
        return await self._scenario.simulate_general_reservation()


async def run() -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "Playwright no está instalado: ejecutar solo en laboratorio aislado.", file=sys.stderr
        )
        return 2

    try:
        async with async_playwright() as api:
            browser = await api.chromium.launch(
                headless=True,
                chromium_sandbox=True,
                timeout=15_000,
                args=["--disable-background-networking"],
            )
            try:
                context = await browser.new_context(service_workers="block", accept_downloads=False)
                try:
                    # The simulated page is set_content() HTML with no external
                    # assets. This route blocks page requests, not OS egress.
                    async def deny_external(route: AbortRoutePort) -> None:
                        await route.abort()

                    await context.route("**/*", deny_external)
                    page = await context.new_page()
                    notices = DemoNotifications()
                    workflow = SyntheticBrowserWorkflow(
                        intents=DemoIntents(),
                        browser=PageDriver(cast("PagePort", page)),
                        notifications=notices,
                    )
                    receipt = await workflow.run(
                        TicketIntent("synthetic-member", "synthetic-event")
                    )
                    if len(notices.notices) != 1:
                        raise RuntimeError("synthetic notice was not emitted exactly once")
                    print(
                        json.dumps(
                            {
                                "mode": "synthetic_only",
                                "result": receipt.outcome.value,
                                "notices": len(notices.notices),
                            }
                        )
                    )
                    return 0
                finally:
                    await asyncio.wait_for(context.close(), timeout=5)
            finally:
                await asyncio.wait_for(browser.close(), timeout=5)
    except Exception as error:
        # No URLs, cookies or credentials are included in the failure output.
        print(f"synthetic_browser_failure: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
