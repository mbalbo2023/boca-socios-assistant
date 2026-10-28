"""Opt-in, single anonymous public-home observation; never logs page content.

This is not part of the controller, CI, Docker runtime or any reservation flow.
No credentials, queue page, CAPTCHA, checkout or user-supplied URL is accepted.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Protocol
from urllib.parse import urlsplit

HOME_URL = "https://bocasocios.bocajuniors.com.ar/"
HOST = "bocasocios.bocajuniors.com.ar"
CHALLENGE_MARKERS = (
    "captcha",
    "queue-it",
    "queueit",
    "waiting room",
    "sala de espera",
    "en fila",
    "acceso denegado",
    "access denied",
    "verificá que sos humano",
    "verifica que eres humano",
)


class RequestPort(Protocol):
    url: str
    method: str
    resource_type: str


class ResponsePort(Protocol):
    status: int


class RoutePort(Protocol):
    request: RequestPort

    async def abort(self) -> None: ...

    async def fetch(self, *, max_redirects: int, timeout: float) -> ResponsePort: ...

    async def fulfill(self, *, response: ResponsePort) -> None: ...


def allow_request(url: str, method: str, kind: str, document_count: int) -> bool:
    """Allow only the first exact root document, with no active page assets."""
    parsed = urlsplit(url)
    if (
        method != "GET"
        or parsed.scheme != "https"
        or parsed.hostname != HOST
        or parsed.netloc != HOST
        or parsed.query
        or parsed.fragment
        or "%" in parsed.path
    ):
        return False
    return kind == "document" and document_count == 0 and url == HOME_URL


def classify(status: int, url: str, visible_text: str) -> str:
    """Discard text after classification; never include it in output or errors."""
    if status != 200 or url != HOME_URL:
        return "blocked"
    text = visible_text.casefold()
    if any(marker in text for marker in CHALLENGE_MARKERS):
        return "challenge"
    if "ingresá a boca socios" in text and "iniciar sesión" in text:
        return "login_visible"
    return "unknown"


async def observe(api: object) -> str:
    """Observe exactly one public document, fail closed on any extra request."""
    # api is the Playwright object in production; a fake is injected in tests.
    browser = await api.chromium.launch(  # type: ignore[attr-defined]
        headless=True,
        chromium_sandbox=True,
        timeout=10_000,
        args=["--disable-background-networking"],
    )
    try:
        context = await browser.new_context(
            accept_downloads=False, service_workers="block", java_script_enabled=False
        )
        try:
            document_count = 0
            blocked = False

            async def route_request(route: RoutePort) -> None:
                nonlocal document_count, blocked
                request = route.request
                if not allow_request(
                    request.url, request.method, request.resource_type, document_count
                ):
                    blocked = True
                    await route.abort()
                    return
                if request.resource_type == "document":
                    document_count += 1
                # Playwright's continue_ follows redirects without another route
                # callback. fetch(max_redirects=0) prevents that extra visit.
                response = await route.fetch(max_redirects=0, timeout=5_000)
                if response.status != 200:
                    blocked = True
                    await route.abort()
                    return
                await route.fulfill(response=response)

            await context.route("**/*", route_request)
            page = await context.new_page()
            response = await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=12_000)
            if blocked or document_count != 1 or response is None:
                return "blocked"
            visible_text = await asyncio.wait_for(page.inner_text("body"), timeout=3)
            if blocked:
                return "blocked"
            return classify(response.status, page.url, visible_text)
        finally:
            await asyncio.wait_for(context.close(), timeout=5)
    finally:
        await asyncio.wait_for(browser.close(), timeout=5)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if (
        argv != ["--ack-one-public-visit"]
        or os.environ.get("BOCA_PUBLIC_OBSERVATION") != "one-shot"
        or os.environ.get("BOCA_OBSERVER_STOP", "1") != "0"
    ):
        print("public_observer_disabled", file=sys.stderr)
        return 2
    try:
        from playwright.async_api import async_playwright

        async def run() -> str:
            async with async_playwright() as api:
                return await asyncio.wait_for(observe(api), timeout=25)

        state = asyncio.run(run())
        if state != "login_visible":
            print(f"public_observer_stopped: {state}", file=sys.stderr)
            return 1
        print(json.dumps({"mode": "public_home_only", "state": state}))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        # Exception messages can contain URLs, headers or browser state.
        print(f"public_observer_stopped: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
