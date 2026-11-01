"""Real Chromium against *inline fictitious HTML*; no public site or URLs visited.

This optional CI image smoke uses ``page.set_content`` only, under Docker
``--network none``. It deliberately never calls ``page.goto`` or fetches a
document. Its result is a structural initial-DOM check, not proof of the
hydrated Boca login, OS FQDN egress readiness or permission to visit Boca.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
from dataclasses import dataclass
from typing import Protocol

from scripts.observe_public_home import LOGIN_URL, document_gate, inspect_login_dom

FORM = (
    '<form><label for="mail">Mail</label><input id="mail" type="email">'
    '<label for="pass">Password</label><input id="pass" type="password">'
    '<button type="submit" disabled>Continue</button></form>'
)
ENABLED_FORM = FORM.replace(" disabled>Continue", ">Continue")
EXTERNAL_CSS = '<link rel="stylesheet" href="https://assets.example.invalid/fixture.css">'
EXTERNAL_JS = '<script src="https://assets.example.invalid/fixture.js"></script>'


@dataclass(frozen=True)
class Fixture:
    name: str
    html: str
    expected: str


FIXTURES = (
    Fixture("ssr_disabled", f"<html><body>{FORM}</body></html>", "login_form_disabled"),
    Fixture(
        "csr_empty_shell",
        f'<html><body><div id="__next"></div>{EXTERNAL_JS}</body></html>',
        "unknown",
    ),
    Fixture(
        "css_dependency",
        f"<html><head>{EXTERNAL_CSS}</head><body>{FORM}</body></html>",
        "unknown",
    ),
    Fixture(
        "hydration_dependency",
        "<html><body>" + FORM + '<script>document.querySelector("button").disabled=false</script>'
        "</body></html>",
        "unknown",
    ),
    Fixture(
        "inline_onload_hydration_dependency",
        '<html><body onload="document.querySelector(&quot;button&quot;).disabled=false">'
        + FORM
        + "</body></html>",
        "unknown",
    ),
    Fixture(
        "generic_onpointerdown_dependency",
        f'<html><body><section onpointerdown="alert(1)">{FORM}</section></body></html>',
        "unknown",
    ),
    Fixture(
        "inline_css_dependency",
        f"<html><head><style>form {{ opacity: 1 }}</style></head><body>{FORM}</body></html>",
        "unknown",
    ),
    Fixture("challenge_preempts_form", f"<html><body>CAPTCHA{FORM}</body></html>", "challenge"),
    Fixture("enabled_submit", f"<html><body>{ENABLED_FORM}</body></html>", "unknown"),
    Fixture("hidden_form", f"<html><body><div hidden>{FORM}</div></body></html>", "unknown"),
    Fixture(
        "aria_hidden_form",
        f'<html><body><div aria-hidden="true">{FORM}</div></body></html>',
        "unknown",
    ),
)


class AbortRoute(Protocol):
    async def abort(self) -> None: ...


def assert_offline_worker_boundary() -> None:
    """Reject an ordinary networked runner even when asked for fake HTML."""
    if os.geteuid() != 10002 or os.getegid() != 10002:
        raise RuntimeError("offline_worker_identity_unverified")
    interfaces = socket.if_nameindex()
    if len(interfaces) != 1 or interfaces[0][0] < 1 or interfaces[0][1] != "lo":
        raise RuntimeError("offline_network_namespace_unverified")


def validate_receipt(value: object) -> dict[str, object]:
    """Validate only fixed, nonsecret values; no page content may appear."""
    if (
        not isinstance(value, dict)
        or set(value) != {"mode", "state", "cases", "page_requests_aborted"}
        or value["mode"] != "offline_public_login_dom"
        or value["state"] != "PASS"
        or type(value["cases"]) is not int
        or value["cases"] != len(FIXTURES)
        or type(value["page_requests_aborted"]) is not int
        or not 1 <= value["page_requests_aborted"] <= len(FIXTURES)
    ):
        raise ValueError("offline_public_dom_receipt_unverified")
    return value


async def run() -> dict[str, object]:
    """Exercise the production DOM predicate in a zero-egress Chromium context."""
    assert_offline_worker_boundary()
    from playwright.async_api import async_playwright

    attempted = 0

    async with async_playwright() as api:
        browser = await api.chromium.launch(
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

                async def deny_all(route: AbortRoute) -> None:
                    nonlocal attempted
                    attempted += 1
                    await route.abort()

                await context.route("**/*", deny_all)
                for fixture in FIXTURES:
                    page = await context.new_page()
                    before = attempted
                    try:
                        await page.set_content(
                            fixture.html, wait_until="domcontentloaded", timeout=5_000
                        )
                        # Prove what the browser actually sees with JS and CSS
                        # resources disabled, then require conservative unknown.
                        if fixture.name in {
                            "css_dependency",
                            "hydration_dependency",
                            "inline_onload_hydration_dependency",
                        }:
                            assert await page.locator('form button[type="submit"]').is_disabled()
                        if fixture.name == "css_dependency":
                            assert await page.locator('form input[type="email"]').is_visible()
                            assert attempted > before  # CSS request was aborted, not fetched.
                        gate = document_gate(200, LOGIN_URL, await page.inner_text("body"))
                        structural = await inspect_login_dom(page) if gate is None else False
                        state = gate or (
                            "login_form_disabled"
                            if structural and attempted == before
                            else "unknown"
                        )
                        if state != fixture.expected:
                            raise RuntimeError("offline_public_dom_fixture_mismatch")
                    finally:
                        await asyncio.wait_for(page.close(), timeout=5)
            finally:
                await asyncio.wait_for(context.close(), timeout=5)
        finally:
            await asyncio.wait_for(browser.close(), timeout=5)

    return validate_receipt(
        {
            "mode": "offline_public_login_dom",
            "state": "PASS",
            "cases": len(FIXTURES),
            "page_requests_aborted": attempted,
        }
    )


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv != ["--run-offline-fixtures"]:
        print("offline_public_dom_disabled", file=sys.stderr)
        return 2
    try:
        receipt = asyncio.run(asyncio.wait_for(run(), timeout=45))
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(f"offline_public_dom_stopped: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
