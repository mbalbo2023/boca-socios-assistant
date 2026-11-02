"""Offline browser proof for the owner Telegram sealing page, using fixed fakes.

Three explicit modes keep dependencies separate: the host renders the fixture
with stdlib; the network-none browser image executes it with Playwright; the
controller image verifies the returned ciphertext with its existing installer.
No dependency is downloaded and no genuine credential or endpoint is used.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import socket
import sys
from pathlib import Path

ORIGIN = "http://localhost:8443"
PAGE_URL = ORIGIN + "/telegram/configurar"
PUBLIC_KEY = "j0DFrbaPJWJK5bIU6nZ6bslNgp09e14a0bpvPiE4KF8"
FINGERPRINT = "eedd883da0a9451593dc0a38e583fb770fa27dbbed209c20404e075e68c4f0c9"
TOKEN = "123456:synthetic_offline_chromium_token"  # noqa: S105 - fixed fake, never sent
CHAT = "1001234567890"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def make_fixture() -> dict[str, str]:
    from boca_socios.panel.telegram_setup_ui import CSP, page

    receipt = json.dumps(
        {"state": "PREPARED", "public_key": PUBLIC_KEY, "fingerprint": FINGERPRINT},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    html = page().decode("utf-8")
    return {"html": html, "csp": CSP, "fragment": "#recipient=" + _b64(receipt)}


def _fixture(path: Path) -> dict[str, str]:
    raw = path.read_bytes()
    if not 1 <= len(raw) <= 40000:
        raise ValueError("fixture_unverified")
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or set(value) != {"html", "csp", "fragment"}
        or any(not isinstance(item, str) for item in value.values())
        or "connect-src 'none'" not in value["csp"]
        or "form-action 'none'" not in value["csp"]
        or not value["fragment"].startswith("#recipient=")
    ):
        raise ValueError("fixture_unverified")
    return value


def _offline_identity() -> None:
    if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (10002,) * 4:
        raise RuntimeError("offline_browser_identity_unverified")
    interfaces = socket.if_nameindex()
    if len(interfaces) != 1 or interfaces[0][1] != "lo":
        raise RuntimeError("offline_network_namespace_unverified")


async def run_offline(path: Path) -> dict[str, object]:
    _offline_identity()
    fixture = _fixture(path)
    from playwright.async_api import Route, async_playwright

    documents = 0
    rejected = 0
    async with async_playwright() as api:
        browser = await api.chromium.launch(
            headless=True,
            chromium_sandbox=True,
            timeout=10000,
            args=["--disable-background-networking"],
        )
        try:
            context = await browser.new_context(
                accept_downloads=False,
                service_workers="block",
                viewport={"width": 800, "height": 1280},
            )
            try:
                await context.grant_permissions(
                    ["clipboard-read", "clipboard-write"], origin=ORIGIN
                )

                async def route_document(route: Route) -> None:
                    nonlocal documents, rejected
                    request = route.request
                    if (
                        documents == 0
                        and request.url == PAGE_URL
                        and request.method == "GET"
                        and request.resource_type == "document"
                        and request.is_navigation_request()
                    ):
                        documents += 1
                        await route.fulfill(
                            status=200,
                            headers={
                                "Content-Type": "text/html; charset=utf-8",
                                "Content-Security-Policy": fixture["csp"],
                                "Cache-Control": "no-store",
                                "Referrer-Policy": "no-referrer",
                            },
                            body=fixture["html"],
                        )
                        return
                    rejected += 1
                    await route.abort()

                await context.route("**/*", route_document)
                page = await context.new_page()
                # Interception fulfills the only document in memory, inside a
                # network-none container. There is no localhost listener.
                await page.goto(PAGE_URL + fixture["fragment"], wait_until="load", timeout=10000)
                await page.wait_for_function(
                    "!document.getElementById('seal').disabled", timeout=5000
                )
                if (
                    page.url != PAGE_URL
                    or await page.locator("#fingerprint").inner_text() != FINGERPRINT
                ):
                    raise RuntimeError("public_receipt_unverified")
                for selector in ("#telegram-token", "#telegram-chat", "#seal", "#copy"):
                    box = await page.locator(selector).bounding_box()
                    if box is None or box["height"] < 52 or box["width"] < 200:
                        raise RuntimeError("tablet_target_unverified")
                # The fixed page's actual CSP must block even a same-origin
                # POST attempted by this synthetic security probe.
                blocked = await page.evaluate(
                    """async () => {
                    try {
                      await fetch('/must-not-send', {method: 'POST', body: 'synthetic-probe'});
                      return false;
                    } catch (_) { return true; }
                    }"""
                )
                if blocked is not True or rejected != 0:
                    raise RuntimeError("csp_connect_unverified")
                await page.locator("#telegram-token").fill(TOKEN)
                await page.locator("#telegram-chat").fill(CHAT)
                await page.locator("#seal").click()
                await page.wait_for_function(
                    "!document.getElementById('copy').disabled", timeout=5000
                )
                ciphertext = await page.locator("#sealed").input_value()
                if (
                    await page.locator("#telegram-token").input_value()
                    or await page.locator("#telegram-chat").input_value()
                ):
                    raise RuntimeError("secret_fields_not_cleared")
                bot_pin = await page.locator("#bot-pin").input_value()
                chat_pin = await page.locator("#chat-pin").input_value()
                for button, expected, destination in (
                    ("#copy-bot", bot_pin, "el secreto BOCA_TELEGRAM_EXPECTED_BOT_ID"),
                    ("#copy-chat", chat_pin, "el secreto BOCA_TELEGRAM_EXPECTED_CHAT_HMAC"),
                    ("#copy", ciphertext, "telegram_envelope de la instalación autorizada"),
                ):
                    await page.locator(button).click()
                    await page.wait_for_function(
                        "text => document.getElementById('result').textContent === text",
                        arg="Valor copiado para " + destination + ".",
                        timeout=5000,
                    )
                    copied = await page.evaluate("navigator.clipboard.readText()")
                    if copied != expected:
                        raise RuntimeError("sealed_values_clipboard_unverified")
                if documents != 1 or rejected != 0:
                    raise RuntimeError("unexpected_browser_request")
                return {
                    "mode": "offline_telegram_setup_ui",
                    "state": "PASS",
                    "document_requests": documents,
                    "other_requests": rejected,
                    "csp_connect_blocked": True,
                    "fields_cleared": True,
                    "history_cleared": True,
                    "ciphertext_copied": True,
                    "ciphertext": ciphertext,
                    "bot_pin": bot_pin,
                    "chat_pin": chat_pin,
                }
            finally:
                await context.close()
        finally:
            await browser.close()


def verify_receipt(value: object) -> None:
    from boca_socios import telegram_bootstrap as bootstrap

    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "mode",
            "state",
            "document_requests",
            "other_requests",
            "csp_connect_blocked",
            "fields_cleared",
            "history_cleared",
            "ciphertext_copied",
            "ciphertext",
            "bot_pin",
            "chat_pin",
        }
        or value["mode"] != "offline_telegram_setup_ui"
        or value["state"] != "PASS"
        or type(value["document_requests"]) is not int
        or value["document_requests"] != 1
        or type(value["other_requests"]) is not int
        or value["other_requests"] != 0
        or any(
            value[key] is not True
            for key in (
                "csp_connect_blocked",
                "fields_cleared",
                "history_cleared",
                "ciphertext_copied",
            )
        )
    ):
        raise ValueError("offline_telegram_ui_receipt_unverified")
    if (
        value["bot_pin"] != TOKEN.partition(":")[0]
        or value["chat_pin"] != hmac.new(TOKEN.encode(), CHAT.encode(), hashlib.sha256).hexdigest()
    ):
        raise ValueError("browser_owner_pins_unverified")
    # These bytes are deliberately public, fixed test data, never deployment keys.
    private = bytes(range(32))
    receipt = bootstrap._receipt(private, "PREPARED")
    if receipt.public_key != PUBLIC_KEY or receipt.fingerprint != FINGERPRINT:
        raise ValueError("synthetic_recipient_unverified")
    envelope = bootstrap._unb64(value["ciphertext"], maximum=bootstrap.MAX_ENVELOPE)
    if bootstrap._decrypt(envelope, private, receipt) != (TOKEN.encode(), CHAT.encode()):
        raise ValueError("browser_ciphertext_unverified")
    if hashlib.sha256(base64.urlsafe_b64decode(PUBLIC_KEY + "=")).hexdigest() != FINGERPRINT:
        raise ValueError("synthetic_fingerprint_unverified")


def main() -> int:
    try:
        if sys.argv[1:] == ["--make-fixture"]:
            print(json.dumps(make_fixture(), sort_keys=True, separators=(",", ":")))
        elif sys.argv[1:] == ["--verify-receipt"]:
            raw = sys.stdin.buffer.read(8193)
            if not 0 < len(raw) <= 8192:
                raise ValueError("receipt_size_unverified")
            verify_receipt(json.loads(raw))
            print("BOCA_TELEGRAM_UI_OFFLINE state=PASS network=none interoperable=true")
        elif len(sys.argv) == 3 and sys.argv[1] == "--run-offline-fixture":
            print(json.dumps(asyncio.run(run_offline(Path(sys.argv[2]))), sort_keys=True))
        else:
            raise ValueError("explicit_offline_mode_required")
    except Exception:
        # No exception string, browser output, envelope or field value is logged.
        print("BOCA_TELEGRAM_UI_OFFLINE state=NO_GO reason=offline_proof_failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
