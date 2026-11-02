"""Opt-in, single anonymous public-login observation; never logs page content.

This is not part of the controller, CI, Docker runtime or any reservation flow.
No credentials, queue page, CAPTCHA, checkout or user-supplied URL is accepted.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import sys
from typing import Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

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
# Only attribute *names* are inspected; this constant expression never reads
# handler values, executes site handlers, fills fields or returns page content.
# Traverse open shadow roots as well as the light DOM to avoid trusting a
# form whose inline lifecycle changes after page scripts become enabled.
INLINE_HANDLER_NAME_PROBE = """() => {
  const pending = [document.documentElement];
  for (let i = 0; i < pending.length; i++) {
    const element = pending[i];
    if (element.getAttributeNames().some(name => name.toLowerCase().startsWith('on')))
      return true;
    pending.push(...element.children);
    if (element.shadowRoot) pending.push(...element.shadowRoot.children);
  }
  return false;
}"""


class RequestPort(Protocol):
    url: str
    method: str
    resource_type: str


class ResponsePort(Protocol):
    status: int


class RoutePort(Protocol):
    request: RequestPort

    async def abort(self) -> None: ...

    async def fetch(
        self, *, max_redirects: int, max_retries: int, timeout: float
    ) -> ResponsePort: ...

    async def fulfill(self, *, response: ResponsePort) -> None: ...


class LocatorPort(Protocol):
    async def count(self) -> int: ...

    async def is_visible(self) -> bool: ...

    async def is_disabled(self) -> bool: ...


class PublicLoginDomPort(Protocol):
    def locator(self, selector: str) -> LocatorPort: ...

    async def evaluate(self, expression: str) -> object: ...


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
    inline_handler = await page.evaluate(INLINE_HANDLER_NAME_PROBE)
    if type(inline_handler) is not bool or inline_handler:
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


async def inspect_rendered_login_dom(page: PublicLoginDomPort) -> bool:
    """Read-only form evidence after bounded offline hydration, never live readiness."""
    if await page.locator("form").count() != 1:
        return False
    if await page.locator(
        'form[aria-hidden="true"], [aria-hidden="true"] form, form[inert], [inert] form'
    ).count():
        return False
    controls = [
        page.locator(selector)
        for selector in (
            'form input[type="email"]',
            'form input[type="password"]',
            'form button[type="submit"], form input[type="submit"]',
        )
    ]
    for control in controls:
        if await control.count() != 1 or not await control.is_visible():
            return False
    return await controls[-1].is_disabled()


def sanitized_resources(values: object) -> list[dict[str, str]]:
    """Keep only bounded public same-origin asset paths; never query/fragment/userinfo."""
    if not isinstance(values, list) or len(values) > 64:
        return []
    found: list[dict[str, str]] = []
    for value in values:
        if not isinstance(value, dict) or set(value) != {"kind", "url"}:
            continue
        kind, raw = value["kind"], value["url"]
        if kind not in {"script", "link", "img", "source"} or not isinstance(raw, str):
            continue
        try:
            parsed = urlsplit(urljoin(LOGIN_URL, raw))
        except ValueError:
            continue
        if (
            parsed.scheme != "https"
            or parsed.netloc != HOST
            or not parsed.path.startswith("/")
            or len(parsed.path) > 256
            or not parsed.path.isascii()
            or any(ord(char) < 33 for char in parsed.path)
        ):
            continue
        item = {"kind": kind, "url": urlunsplit(("https", HOST, parsed.path, "", ""))}
        if item not in found:
            found.append(item)
    return found


async def observe(
    api: object,
    *,
    check_dom: bool = False,
    proxy_server: str | None = None,
    evidence: dict[str, object] | None = None,
) -> str:
    """Observe exactly one public document, fail closed on any extra request."""
    # api is the Playwright object in production; a fake is injected in tests.
    proxy_args = {} if proxy_server is None else {"proxy": {"server": proxy_server}}
    browser = await api.chromium.launch(  # type: ignore[attr-defined]
        headless=True,
        chromium_sandbox=True,
        timeout=10_000,
        args=["--disable-background-networking"],
        **proxy_args,
    )
    try:
        context = await browser.new_context(
            accept_downloads=False,
            service_workers="block",
            java_script_enabled=False,
            **proxy_args,
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
                if evidence is not None:
                    evidence["route_fetch_count"] = document_count
                response = await route.fetch(max_redirects=0, max_retries=0, timeout=5_000)
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
            gate = document_gate(response.status, page.url, visible_text)
            if gate is not None:
                return gate
            if evidence is not None:
                values = await asyncio.wait_for(
                    page.locator("script[src], link[href], img[src], source[src]").evaluate_all(
                        "nodes => ({truncated: nodes.length > 64, items: "
                        "nodes.slice(0, 64).map(node => ({kind: node.tagName.toLowerCase(), "
                        "url: node.getAttribute('src') || node.getAttribute('href') || ''}))})"
                    ),
                    timeout=3,
                )
                if not isinstance(values, dict) or type(values.get("truncated")) is not bool:
                    raise ValueError("invalid resource inventory")
                evidence["referenced_assets"] = sanitized_resources(values.get("items"))
                evidence["inventory_truncated"] = values["truncated"]
                evidence["discarded_assets"] = discarded_assets
            if check_dom:
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
    isolated_view = argv == ["--isolated-one-get"]
    if (
        not (public_view or dom_view or isolated_view)
        or os.environ.get("BOCA_PUBLIC_OBSERVATION") != "one-shot"
        or os.environ.get("BOCA_OBSERVER_STOP", "1") != "0"
    ):
        print("public_observer_disabled", file=sys.stderr)
        return 2
    try:
        proxy_server = None
        evidence: dict[str, object] | None = None
        if isolated_view:
            proxy_ip = ipaddress.IPv4Address(os.environ.get("BOCA_PUBLIC_PROXY_IP", ""))
            if not proxy_ip.is_private or proxy_ip.is_loopback or proxy_ip.is_unspecified:
                raise ValueError("invalid isolated proxy")
            proxy_server = f"http://{proxy_ip}:18080"
            evidence = {
                "route_fetch_count": 0,
                "referenced_assets": [],
                "inventory_truncated": False,
                "discarded_assets": 0,
            }
        from playwright.async_api import async_playwright

        async def run() -> str:
            async with async_playwright() as api:
                if isolated_view:
                    return await asyncio.wait_for(
                        observe(api, check_dom=True, proxy_server=proxy_server, evidence=evidence),
                        timeout=25,
                    )
                return await asyncio.wait_for(observe(api, check_dom=dom_view), timeout=25)

        state = asyncio.run(run())
        if isolated_view:
            print(
                json.dumps({"mode": "initial_public_document", "state": state, **(evidence or {})})
            )
            return 0 if state == "login_form_disabled" else 1
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
