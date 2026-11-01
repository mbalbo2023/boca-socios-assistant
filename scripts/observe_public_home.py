"""Opt-in, single anonymous public-login observation; never logs page content.

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
LOGIN_URL = HOME_URL + "auth/login"
HOST = "bocasocios.bocajuniors.com.ar"
CHALLENGE_MARKERS = (
    "captcha",
    "queue-it",
    "queueit",
    "queue",
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


class LocatorPort(Protocol):
    async def count(self) -> int: ...

    async def is_visible(self) -> bool: ...

    async def is_disabled(self) -> bool: ...


class PublicLoginDomPort(Protocol):
    def locator(self, selector: str) -> LocatorPort: ...


def allow_request(url: str, method: str, kind: str, document_count: int) -> bool:
    """Allow only the first exact public-login document, with no active assets."""
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
    return kind == "document" and document_count == 0 and url == LOGIN_URL


def expected_discarded_asset(url: str, method: str, kind: str) -> bool:
    """Discard ordinary same-origin display assets without treating them as navigation."""
    parsed = urlsplit(url)
    if method != "GET" or parsed.scheme != "https" or parsed.netloc != HOST:
        return False
    if any(marker in (parsed.path + parsed.query).casefold() for marker in CHALLENGE_MARKERS):
        return False
    if kind in {"script", "stylesheet", "font", "image", "media"}:
        return True
    return kind == "other" and parsed.path == "/favicon.ico" and not parsed.query


def document_gate(status: int, url: str, visible_text: str) -> str | None:
    """Stop bad responses and challenges before interpreting public DOM."""
    if status != 200 or url != LOGIN_URL:
        return "blocked"
    text = visible_text.casefold()
    if any(marker in text for marker in CHALLENGE_MARKERS):
        return "challenge"
    return None


def classify(status: int, url: str, visible_text: str) -> str:
    """Discard text after classification; never include it in output or errors."""
    gate = document_gate(status, url, visible_text)
    if gate is not None:
        return gate
    text = visible_text.casefold()
    if "ingresá a boca socios" in text and "iniciar sesión" in text:
        return "login_visible"
    return "unknown"


async def inspect_login_dom(page: PublicLoginDomPort) -> bool:
    """Prove only a self-contained initial form, never hydrated-page readiness.

    JavaScript and external assets are blocked for the one-GET contract. A
    stylesheet could conceal otherwise visible controls, and a script could
    replace the form or change its disabled state. Such incomplete snapshots
    are unknown even when the initial controls appear structurally valid.
    """
    if await page.locator('script, link[rel~="stylesheet"], style').count():
        return False
    if await page.locator(
        'form[aria-hidden="true"], [aria-hidden="true"] form, form[inert], [inert] form'
    ).count():
        return False
    # Requiring one form ties each typed control and disabled submit to one form,
    # while allowing the visible copy and accessible labels to change safely.
    form = page.locator("form")
    if await form.count() != 1:
        return False
    email = page.locator('form input[type="email"]')
    password = page.locator('form input[type="password"]')
    submit = page.locator('form button[type="submit"], form input[type="submit"]')
    # Missing, hidden or duplicated controls, CSR shells or enabled submit are unknown.
    for item in (email, password, submit):
        if await item.count() != 1 or not await item.is_visible():
            return False
    return await submit.is_disabled()


async def observe(api: object, *, check_dom: bool = False) -> str:
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
            discarded_assets = 0

            async def route_request(route: RoutePort) -> None:
                nonlocal document_count, blocked, discarded_assets
                request = route.request
                if not allow_request(
                    request.url, request.method, request.resource_type, document_count
                ):
                    if expected_discarded_asset(request.url, request.method, request.resource_type):
                        discarded_assets += 1
                    else:
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
            response = await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=12_000)
            if blocked or document_count != 1 or response is None:
                return "blocked"
            visible_text = await asyncio.wait_for(page.inner_text("body"), timeout=3)
            if blocked:
                return "blocked"
            if check_dom:
                gate = document_gate(response.status, page.url, visible_text)
                if gate is not None:
                    return gate
                # This reads selectors/state only. No fill, click or submit.
                dom_ok = await asyncio.wait_for(inspect_login_dom(page), timeout=3)
                if blocked:
                    return "blocked"
                # Any aborted display asset makes actual visibility/state
                # uncertain even if the initial HTML contains a valid form.
                return "login_form_disabled" if dom_ok and not discarded_assets else "unknown"
            return classify(response.status, page.url, visible_text)
        finally:
            await asyncio.wait_for(context.close(), timeout=5)
    finally:
        await asyncio.wait_for(browser.close(), timeout=5)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    public_view = argv == ["--ack-one-public-visit"]
    dom_view = argv == ["--ack-one-public-visit", "--check-public-login-dom"]
    if (
        not (public_view or dom_view)
        or os.environ.get("BOCA_PUBLIC_OBSERVATION") != "one-shot"
        or os.environ.get("BOCA_OBSERVER_STOP", "1") != "0"
    ):
        print("public_observer_disabled", file=sys.stderr)
        return 2
    try:
        from playwright.async_api import async_playwright

        async def run() -> str:
            async with async_playwright() as api:
                return await asyncio.wait_for(observe(api, check_dom=dom_view), timeout=25)

        state = asyncio.run(run())
        if state != ("login_form_disabled" if dom_view else "login_visible"):
            print(f"public_observer_stopped: {state}", file=sys.stderr)
            return 1
        print(json.dumps({"mode": "public_login_only", "state": state}))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        # Exception messages can contain URLs, headers or browser state.
        print(f"public_observer_stopped: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
